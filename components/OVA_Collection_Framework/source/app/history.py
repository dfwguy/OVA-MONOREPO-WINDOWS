#!/usr/bin/env python3
"""Durable Slurm evidence capture. SQLite checkpoint, immutable payloads, atomic Parquet generations."""
import os,sys,re,json,hashlib,gzip,sqlite3,time,subprocess,tempfile,shlex,threading,tarfile,io
from pathlib import Path
from datetime import datetime,timezone
import pyarrow as pa, pyarrow.parquet as pq
from durable import atomic_write, sync_directory, sync_file
from settings import CONFIG, ROOT_PATH, MANIFEST_DIRS, LOCAL_ROOTS, CONTROLLER_LOG, COMPLETION_LOG, FIRST_JOB_ID, MAX_GAP_SPAN, manifests, ssh_args
ROOT=ROOT_PATH; SLURM=str(Path(CONFIG['slurm_bin']))+'/'
ROOT.mkdir(parents=True,exist_ok=True); [ (ROOT/p).mkdir(exist_ok=True) for p in ['state','raw','lake','export'] ]
def now(): return datetime.now(timezone.utc).isoformat()
def db():
 c=sqlite3.connect(ROOT/'state/index.sqlite',timeout=60);c.execute('pragma journal_mode=WAL');c.executescript('''create table if not exists metric_parser_files(source text primary key,version text,parser text); create table if not exists validations(artifact_id text primary key,job_id integer,source text,status text,summary text); create table if not exists remote_coverage(job_id integer,host text,inventory_count integer,captured_count integer,status text,updated_utc text,error text,primary key(job_id,host)); create table if not exists files(source text primary key,size integer,mtime real,sha text,version text,job_id integer); create table if not exists artifacts(version text primary key,job_id integer,source text,sha256 text,stored_sha256 text,bytes integer,stored_bytes integer,captured_utc text,redacted integer,encoding text,kind text);create table if not exists jobs(job_id integer primary key,metadata text,coverage text,updated_utc text);create table if not exists metrics(id text primary key,job_id integer,artifact_id text,line_no integer,iteration integer,metric text,value real,unit text,raw_line text);create table if not exists errors(id integer primary key,utc text,source text,message text);create table if not exists events(id integer primary key,utc text,job_id integer,kind text,evidence text);''');
 try:c.execute('alter table errors add column resolved_utc text')
 except sqlite3.OperationalError:pass
 return c
def redact(b):
 # Preserve non-secret bytes exactly; secret values are replaced, with original hash retained.
 n=0
 if b.lstrip().startswith((b'{',b'[')):
  try:
   obj=json.loads(b)
   def walk(x):
    nonlocal n
    if isinstance(x,dict):
     for key in list(x):
      if re.fullmatch(r'password|passwd|secret|access_token|refresh_token|api_key|authorization|private_key',key,re.I):x[key]='[REDACTED]';n+=1
      else:walk(x[key])
    elif isinstance(x,list):
     for y in x:walk(y)
   walk(obj)
   if n:return json.dumps(obj,ensure_ascii=False).encode(),n
  except Exception:pass
 def sub(m):
  nonlocal n;n+=1;return m.group(1)+b'[REDACTED]'
 b=re.sub(rb'(?im)((?:password|passwd|secret|access_token|refresh_token|api_key|authorization|private_key)["\']?\s*[=:]\s*["\']?)[^\s,"\'\r\n}]+',sub,b)
 b,k=re.subn(rb'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----.*?-----END (?:OPENSSH |RSA |EC )?PRIVATE KEY-----',b'[REDACTED PRIVATE KEY]',b,flags=re.S);n+=k
 return b,n
def kind(p):
 if p.endswith(('.json','.yaml','.yml','.toml')):return 'configuration_or_validation'
 if p.endswith(('.sh','.py','.sbatch','.conf')):return 'script_or_configuration'
 return 'raw_log_or_report'
def jid(p):
 m=re.search(r'(?:job|JobId[= ])(\d+)',p,re.I)
 if m:return int(m[1])
 m=re.search(r'_(\d+)(?:_\d+)?\.out$',p)
 return int(m[1]) if m else 0
METRIC=[('iteration_time',r'elapsed time per iteration \(ms\):\s*([\d.]+)','ms'),('modeled_throughput',r'throughput per GPU \(TFLOP/s/GPU\):\s*([\d.]+)','TFLOP/s/GPU'),('lm_loss',r'lm loss:\s*([\d.eE+-]+)','dimensionless'),('step_time',r'Step Time\s*:\s*(\d+(?:\.\d+)?)','s'),('modeled_throughput',r'GPU utilization:\s*([\d.]+)MODEL_TFLOP/s/GPU','TFLOP/s/GPU')]
def record(c,source,b,size=None,mtime=None,job=None,force=False):
 sha=hashlib.sha256(b).hexdigest();j=jid(source) if job is None else job
 if not j and source.endswith('.json'):
  try:
   x=json.loads(b);candidate=x.get('job_id') if isinstance(x,dict) else None
   if isinstance(candidate,int):j=candidate
  except Exception:pass
 v=hashlib.sha256((source+'\0'+sha).encode()).hexdigest(); old=c.execute('select version from files where source=?',(source,)).fetchone()
 if Path(source).suffix in ('.log','.out','.err') and not c.execute("select 1 from metric_parser_files where source=? and version=? and parser='2026-10-07.portable1'",(source,v)).fetchone():force=True
 if old and old[0]==v and not force:
  c.execute('update errors set resolved_utc=? where source=? and resolved_utc is null',(now(),source));return
 clean,n=redact(b); stored=hashlib.sha256(clean).hexdigest(); target=ROOT/'raw'/stored[:2]/(stored+'.gz');target.parent.mkdir(exist_ok=True)
 if not target.exists():
  atomic_write(target,gzip.compress(clean,mtime=0))
 c.execute('update errors set resolved_utc=? where source=? and resolved_utc is null',(now(),source))
 c.execute('insert or ignore into artifacts values (?,?,?,?,?,?,?,?,?,?,?)',(v,j,source,sha,stored,len(b),len(clean),now(),int(n>0),'binary-preserved/redacted' if n else 'binary-preserved',kind(source)))
 c.execute('insert or replace into files values (?,?,?,?,?,?)',(source,size or len(b),mtime or time.time(),sha,v,j))
 if j:c.execute('insert or ignore into jobs values (?,?,?,?)',(j,'{}','artifacts_only',now()))
 if source.endswith('.json') and len(clean)<10*1024*1024:
  try:
   x=json.loads(clean)
   if isinstance(x,dict):
    summary={k:x[k] for k in ['status','passed','pass','ok','ready','failures','errors','runtime_gate','runtime_gate_failure','validation_status','qualification_status','all_rail_validation','final_state','exit_code'] if k in x}
    if summary:
     status='PASS' if str(x.get('status','')).upper()=='PASS' or x.get('passed') is True or x.get('ok') is True else 'FAIL' if str(x.get('status','')).upper()=='FAIL' or x.get('passed') is False or x.get('ok') is False else 'EVIDENCE'
     c.execute('insert or replace into validations values(?,?,?,?,?)',(v,j,source,status,json.dumps(summary)))
  except Exception:pass
 if len(clean)>=100*1024*1024 and not Path(source).name.startswith('nccl-'):err(c,source+'#metrics','Raw bytes retained; metric extraction deferred above100MiB, not included in score table')
 if len(clean)<100*1024*1024 and not Path(source).name.startswith('nccl-'):
  c.execute('delete from metrics where artifact_id=?',(v,))
  import bisect
  text=clean.decode('utf-8','replace');newlines=[m.start() for m in re.finditer('\n',text)];iterations=list(re.finditer(r'iteration\s+(\d+)\s*/',text))
  def save(metric,value,unit,pos,iteration):
   ln=bisect.bisect_right(newlines,pos)+1;start=text.rfind('\n',0,pos)+1;end=text.find('\n',pos);line=text[start:end if end>=0 else len(text)]
   c.execute('insert or replace into metrics values (?,?,?,?,?,?,?,?,?)',(hashlib.sha256(f'{source}:{pos}:{metric}'.encode()).hexdigest(),j,v,ln,iteration,metric,value,unit,line[:3000]))
  for index,im in enumerate(iterations):
   iteration=int(im[1]);end=iterations[index+1].start() if index+1<len(iterations) else len(text);segment=text[im.start():end]
   for metric,pat,unit in METRIC[:3]:
    match=re.search(pat,segment,re.I)
    if match:save(metric,float(match[1]),unit,im.start()+match.start(),iteration)
  # Header and iteration streams occasionally share/interleave stdout lines. Pair ordered records, not line boundaries.
  headers=list(re.finditer(r'Step Time\s*:\s*(\d+(?:\.\d+)?)s?[^\n]*?GPU utilization:\s*(\d+(?:\.\d+)?)MODEL_TFLOP/s/GPU',text))
  for index,header in enumerate(headers):
   if index>=len(iterations):break  # A live header can precede the still-unflushed iteration record.
   iteration=int(iterations[index][1]);save('step_time',float(header[1]),'s',header.start(),iteration);save('modeled_throughput',float(header[2]),'TFLOP/s/GPU',header.start(),iteration)

  c.execute('insert or replace into metric_parser_files values(?,?,?)',(source,v,'2026-10-07.portable1'))
 return v

def err(c,source,e):c.execute('insert into errors(utc,source,message) values (?,?,?)',(now(),source,redact(str(e).encode())[0].decode('utf-8','replace')[:1500]))
def reconcile_manifests(c):
 for p in list(manifests()):
  if not p.exists():continue
  try:
   x=json.loads(p.read_text());j=int(x.get('job_id',jid(str(p))));c.execute('update errors set resolved_utc=? where source=? and resolved_utc is null',(now(),str(p)));old=c.execute('select metadata from jobs where job_id=?',(j,)).fetchone();merged=json.loads(old[0]) if old else {};merged.update(x);clean,_=redact(json.dumps(merged).encode());art=c.execute('select count(*) from artifacts where job_id=?',(j,)).fetchone()[0];coverage='manifest_and_artifacts' if art else 'manifest_only'
   if art and x.get('final_state')=='COMPLETED' and x.get('runtime_gate',{}).get('passed'):coverage='validated_completed_with_artifacts'
   c.execute('insert or replace into jobs values (?,?,?,?)',(j,clean.decode(),coverage,now()))
  except Exception as e:err(c,str(p),e)
 # Recover ID evidence first, rather than waiting for large log backfill.
 p=CONTROLLER_LOG
 try:
  b=p.read_bytes();record(c,str(p),b,p.stat().st_size,p.stat().st_mtime)
  for m in re.finditer(r'(?:JobId|JobID)=?(\d+)',b.decode('utf-8','replace')):
   j=int(m[1]);c.execute('insert or ignore into jobs values (?,?,?,?)',(j,json.dumps({'controller_evidence':str(p)}),'controller_events_only',now()))
 except Exception as e:err(c,str(p),e)
 p=COMPLETION_LOG
 if p.exists():
  try:
   b=p.read_bytes();record(c,str(p),b,p.stat().st_size,p.stat().st_mtime)
   for line in b.decode('utf-8','replace').splitlines():
    fields=dict(re.findall(r'(\w+)=([^\s]+)',line));j=int(fields.get('JobId',0))
    if j:
     old=c.execute('select metadata,coverage from jobs where job_id=?',(j,)).fetchone();x=json.loads(old[0]) if old else {};x['completion']=fields;c.execute('insert or replace into jobs values(?,?,?,?)',(j,json.dumps(x),old[1] if old else 'completion_only',now()))
  except Exception as e:err(c,str(p),e)
 c.execute("update jobs set coverage='controller_metadata_and_artifacts' where coverage='controller_events_only' and job_id in(select distinct job_id from artifacts where job_id>0)")
 c.commit()

def local_scan(c):
 associations=[]
 roots=LOCAL_ROOTS+[ROOT/'state/job-manifests']+[p.parent for p in [CONTROLLER_LOG,COMPLETION_LOG]]
 for m in manifests():
  try:
   x=json.loads(m.read_text());e=x.get('experiment');
   if e:
    associations.append((e,int(x.get('job_id',0))))
    if Path(e).is_dir() and any(Path(e).resolve().is_relative_to(r.resolve()) for r in LOCAL_ROOTS):roots.append(Path(e))
  except Exception:pass
 excluded={'install','images','datasets','hf-cache','checkpoints','.git','venv','__pycache__'}
 extensions={'.out','.log','.err','.json','.jsonl','.yaml','.yml','.md','.txt','.sh','.py','.sbatch','.conf'}
 visited=set()
 for root in dict.fromkeys(roots):
  for parent,dirs,files in os.walk(root):
   dirs[:]=[d for d in dirs if d not in excluded and not d.startswith('.')]
   if root in [CONTROLLER_LOG.parent,COMPLETION_LOG.parent] and root not in LOCAL_ROOTS:dirs[:]=[]
   for name in files:
    p=Path(parent)/name
    if str(p) in visited:continue
    visited.add(str(p))
    scheduler_source=any(p.parent.resolve()==log.parent.resolve() and p.name.startswith(log.name) for log in [CONTROLLER_LOG,COMPLETION_LOG])
    if root in [CONTROLLER_LOG.parent,COMPLETION_LOG.parent] and root not in LOCAL_ROOTS and not scheduler_source:continue
    if (not scheduler_source and p.suffix not in extensions and not name.endswith('-stage.tar.gz')) or re.search(r'credential|secret|token|\.pem|id_rsa|id_ed25519',name,re.I):continue
    try:
     resolved=p.resolve()
     artifact_allowed=any(resolved.is_relative_to(r.resolve()) for r in LOCAL_ROOTS+[ROOT/'state'])
     scheduler_allowed=any(p.parent.resolve()==log.parent.resolve() and p.name.startswith(log.name) and resolved.parent==log.parent.resolve() for log in [CONTROLLER_LOG,COMPLETION_LOG])
     if not (artifact_allowed or scheduler_allowed):
      err(c,str(p),'outside approved local roots');continue
     if not p.is_file():continue
     s=p.stat();src=str(p);old=c.execute('select size,mtime from files where source=?',(src,)).fetchone()
     if old and old==(s.st_size,s.st_mtime):
      parsed=c.execute("select 1 from metric_parser_files where source=? and parser='2026-10-07.portable1'",(src,)).fetchone()
      if parsed or s.st_size>int(CONFIG.get('local_stream_threshold_bytes',256*1024*1024)) or not name.endswith(('.log','.out','.err')):continue
     if s.st_size>int(CONFIG.get('local_stream_threshold_bytes',256*1024*1024)):
      if name.endswith('-stage.tar.gz'):err(c,src,'oversized archive adapter required');continue
      from streaming import capture
      capture(c,p,job=next((j for prefix,j in associations if src.startswith(prefix+'/')),None));continue
     b=p.read_bytes()
     if name.endswith('-stage.tar.gz'):
      with tarfile.open(fileobj=io.BytesIO(b),mode='r:gz') as tar:
       for member in tar.getmembers():
        if member.isfile() and member.size<32*1024*1024 and Path(member.name).suffix in extensions:
         if not re.search(r'credential|secret|token|private',member.name,re.I):record(c,src+'!/'+member.name,tar.extractfile(member).read(),job=jid(src))
      c.execute('insert or replace into files values (?,?,?,?,?,?)',(src,s.st_size,s.st_mtime,hashlib.sha256(b).hexdigest(),'archive-container',jid(src)))
     else:record(c,src,b,s.st_size,s.st_mtime,job=next((j for prefix,j in associations if src.startswith(prefix+'/')),None))
     if p.parent.resolve() in [CONTROLLER_LOG.parent.resolve(),COMPLETION_LOG.parent.resolve()]:
      if name.endswith('.gz'):
       with gzip.open(p,'rb') as rotated:
        decoded=rotated.read(256*1024*1024+1)
       if len(decoded)>256*1024*1024:err(c,src,'Oversized compressed scheduler log requires streaming parser');continue
       text=decoded.decode('utf-8','replace')
      else:text=b.decode('utf-8','replace')
      for m in re.finditer(r'(?:JobId|JobID|JobId)=?(\d+)',text):
       j=int(m[1]);c.execute('insert or ignore into jobs values (?,?,?,?)',(j,json.dumps({'controller_evidence':src}),'controller_events_only',now()))
      if name.startswith(COMPLETION_LOG.name):
       for line in text.splitlines():
        fields=dict(re.findall(r'(\w+)=([^\s]+)',line));j=int(fields.get('JobId',0))
        if j:
         old=c.execute('select metadata,coverage from jobs where job_id=?',(j,)).fetchone();x=json.loads(old[0]) if old else {};x['completion']=fields;c.execute('insert or replace into jobs values (?,?,?,?)',(j,json.dumps(x),old[1] if old else 'completion_only',now()))
     c.commit()
    except Exception as e:err(c,str(p),e);c.commit()

def command(args,timeout=25):return subprocess.run(args,capture_output=True,timeout=timeout,check=True,env=dict(os.environ,TZ='UTC')).stdout

def live_scan(c,capture_stdout=False):
 try:
  b=command([SLURM+'scontrol','show','jobs','-o']);record(c,'slurm://controller/jobs-current',b)
  for line in b.decode().splitlines():
   fields=dict(re.findall(r'(\w+)=([^\s]+)',line));j=int(fields.get('JobId',0))
   if not j:continue
   old=c.execute('select metadata,coverage from jobs where job_id=?',(j,)).fetchone();x=json.loads(old[0]) if old else {};x['slurm']=fields;c.execute('insert or replace into jobs values (?,?,?,?)',(j,json.dumps(x),old[1] if old and x.get('final_state') else 'live_metadata_and_artifacts',now()));record(c,f'slurm://job{j}/metadata',line.encode(),job=j)
   # Save exact sbatch submitted script while Slurm retains it. No environment export (may hold credentials).
   if fields.get('BatchFlag')=='0':
    c.execute('update errors set resolved_utc=? where source=? and resolved_utc is null',(now(),f'job{j}/batch_script'))
    x['submitted_script_status']='not_applicable: interactive srun allocation (BatchFlag=0)';c.execute('update jobs set metadata=? where job_id=?',(json.dumps(x),j))
   elif not c.execute('select 1 from files where source=?',(f'slurm://job{j}/batch_script.sh',)).fetchone():
    fd,tmp=tempfile.mkstemp();os.close(fd)
    try:
     command([SLURM+'scontrol','write','batch_script',str(j),tmp]);record(c,f'slurm://job{j}/batch_script.sh',Path(tmp).read_bytes(),job=j)
    except Exception as e:err(c,f'job{j}/batch_script',e)
    finally:Path(tmp).unlink(missing_ok=True)
   host=fields.get('BatchHost');path=fields.get('StdOut')
   c.commit()
   if capture_stdout and host and host!='(null)' and path and path.startswith('/'):
    try:
     remote="python3 -c "+shlex.quote("from pathlib import Path; import sys; p=Path("+repr(path)+"); sys.stdout.buffer.write(p.read_bytes() if p.exists() else b'')")
     b=command(ssh_args(host)+[remote],20)
     if b:record(c,f'ssh://{host}{path}',b,job=j)
    except Exception as e:err(c,f'ssh://{host}{path}',e)
  c.execute("update errors set resolved_utc=? where source='live-slurm' and resolved_utc is null",(now(),));c.commit()
 except Exception as e:err(c,'live-slurm',e);c.commit()

def publish(c):
 import fcntl
 with open(ROOT/"state/publish.lock","w") as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  c.commit();c.execute("BEGIN")
  try:return _publish(c)
  finally:c.commit()

def _publish(c):
 import shutil
 if shutil.disk_usage(ROOT).free<2*1024**3:raise RuntimeError('Disk below2GiB free: evidence collection degraded; free space before further publication')
 max_seen=c.execute('select coalesce(max(job_id),0) from jobs').fetchone()[0]
 if max_seen-FIRST_JOB_ID>MAX_GAP_SPAN:raise RuntimeError('Job ID span exceeds configured gap budget; choose a new cluster epoch/root or adapt interval gaps')
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f');gen=ROOT/'lake'/('generation-'+stamp);gen.mkdir()
 schemas={'jobs':[('job_id',pa.int64()),('metadata',pa.string()),('coverage',pa.string()),('updated_utc',pa.string())], 'artifacts':[('version',pa.string()),('job_id',pa.int64()),('source',pa.string()),('sha256',pa.string()),('stored_sha256',pa.string()),('bytes',pa.int64()),('stored_bytes',pa.int64()),('captured_utc',pa.string()),('redacted',pa.int64()),('encoding',pa.string()),('kind',pa.string())], 'metrics':[('id',pa.string()),('job_id',pa.int64()),('artifact_id',pa.string()),('line_no',pa.int64()),('iteration',pa.int64()),('metric',pa.string()),('value',pa.float64()),('unit',pa.string()),('raw_line',pa.string())], 'errors':[('id',pa.int64()),('utc',pa.string()),('source',pa.string()),('message',pa.string()),('resolved_utc',pa.string())]}
 schemas['validations']=[('artifact_id',pa.string()),('job_id',pa.int64()),('source',pa.string()),('status',pa.string()),('summary',pa.string())]
 schemas['remote_coverage']=[('job_id',pa.int64()),('host',pa.string()),('inventory_count',pa.int64()),('captured_count',pa.int64()),('status',pa.string()),('updated_utc',pa.string()),('error',pa.string())]
 schemas['jobs'] += [('workload',pa.string()),('model',pa.string()),('dtype',pa.string()),('gpus',pa.int64()),('state',pa.string()),('start_utc',pa.string()),('end_utc',pa.string()),('nodes',pa.string()),('completion_state',pa.string()),('validation_state',pa.string()),('qualification_status',pa.string())]
 schemas['metric_observations']=schemas['metrics']
 for table,fields in schemas.items():
  if table=='metrics':
   rows=c.execute('''select id,job_id,artifact_id,line_no,iteration,metric,value,unit,raw_line from (select m.*,row_number() over(partition by m.job_id,m.iteration,m.metric order by case when a.source like 'ssh://%' then 1 else 0 end,a.captured_utc desc) as preferred from metrics m join artifacts a on a.version=m.artifact_id where m.artifact_id in (select version from files) and m.job_id>0 and m.iteration is not null) where preferred=1''').fetchall()
  elif table=='metric_observations':rows=c.execute('select * from metrics where artifact_id in (select version from files)').fetchall()
  else:rows=c.execute('select * from '+table).fetchall()
  schema=pa.schema(fields);data=[dict(zip([f[0] for f in fields],r)) for r in rows]
  if table=='jobs':
   for r in data:
    x=json.loads(r['metadata']);sl=x.get('slurm',{});co=x.get('completion',{});w=x.get('workload') or sl.get('JobName') or co.get('Name') or '';dtype=next((d for d in ['nvfp4','bf16','fp8','fp4','fp16'] if d in w.lower()),'unknown');r.update(workload=w,model=re.sub(r'_(?:nvfp4|bf16|fp8|fp4|fp16).*','',w),dtype=dtype,gpus=x.get('gpus') or (int(re.search(r'gres/gpu[=:](\d+)',sl.get('AllocTRES',''))[1]) if re.search(r'gres/gpu[=:](\d+)',sl.get('AllocTRES','')) else None),state=co.get('JobState') or sl.get('JobState') or (x.get('final_state') if x.get('final_state') in ['COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL'] else None) or 'UNKNOWN',start_utc=x.get('started_utc') or sl.get('StartTime') or co.get('StartTime'),end_utc=x.get('completed_utc') or sl.get('EndTime') or co.get('EndTime'),nodes=json.dumps(x.get('nodes') or sl.get('NodeList') or co.get('NodeList') or []),completion_state=co.get('JobState'),validation_state=x.get('final_state') if x.get('final_state') not in ['COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL',None] else ('PASS' if x.get('runtime_gate',{}).get('passed') is True else 'FAIL' if x.get('runtime_gate',{}).get('passed') is False else 'UNKNOWN'),qualification_status=x.get('qualification_status'))
   known={r['job_id'] for r in data};max_known=max(known,default=0)
   for j in range(FIRST_JOB_ID,max_known+1):
    if j not in known:data.append({'job_id':j,'metadata':'{}','coverage':'no_recovered_evidence','updated_utc':now(),'state':'UNKNOWN','workload':'','model':'','dtype':'unknown','gpus':None,'start_utc':None,'end_utc':None,'nodes':'[]'})
  pq.write_table(pa.Table.from_pylist(data,schema=schema),gen/(table+'.parquet'),compression='zstd')
 maxid=c.execute('select coalesce(max(job_id),0) from jobs').fetchone()[0]
 gaps=[{'job_id':j,'status':'no_recovered_evidence','explanation':'No job record/log recovered from available sources; not assumed successful.'} for j in range(FIRST_JOB_ID,maxid+1) if not c.execute('select 1 from jobs where job_id=?',(j,)).fetchone()]
 pq.write_table(pa.Table.from_pylist(gaps,schema=pa.schema([('job_id',pa.int64()),('status',pa.string()),('explanation',pa.string())])),gen/'gaps.parquet')
 # Raw payloads are immutable Parquet chunks, independently readable without gzip sidecars.
 payload=ROOT/'lake/payloads';payload.mkdir(exist_ok=True)
 for sha, in c.execute('select distinct stored_sha256 from artifacts'):
  out=payload/(sha+'.parquet')
  if out.exists():continue
  from streaming import publish_payload
  publish_payload(ROOT/'raw'/sha[:2]/(sha+'.gz'),out,sha)
 status={'updated_utc':now(),'generation':str(gen),'job_count':c.execute('select count(*) from jobs').fetchone()[0],'max_job_id':maxid,'missing_job_ids':[g['job_id'] for g in gaps],'artifact_versions':c.execute('select count(*) from artifacts').fetchone()[0],'metrics':pq.read_metadata(gen/'metrics.parquet').num_rows,'metric_observations':c.execute('select count(*) from metrics').fetchone()[0],'error_count':c.execute('select count(*) from errors').fetchone()[0],'open_error_count':c.execute('select count(*) from errors where resolved_utc is null').fetchone()[0],'completion_stream':str(COMPLETION_LOG),'limitations':'Only configured readable sources are captured; sacct/job steps require an accounting adapter. Files deleted before capture cannot be reconstructed. Gaps/errors remain explicit.'}
 import shutil
 status.update(schema_version=1,parser_version='2026-10-07.portable1',site=CONFIG['site'],slurm_cluster=CONFIG['cluster'],cluster_epoch=CONFIG['epoch'],slurm_display_timezone='UTC',raw_log_timestamp_timezone='source-native / unverified; raw strings preserved, not labelled UTC',metric_units={'iteration_time':'ms','step_time':'s','modeled_throughput':'TFLOP/s/GPU (model computed)','lm_loss':'dimensionless'},coverage_by_type=dict(c.execute('select coverage,count(*) from jobs group by coverage').fetchall()))
 status['implementation_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'app').glob('*.py')}
 status['disk_free_bytes']=shutil.disk_usage(ROOT).free;status['disk_warning']=status['disk_free_bytes']<20*1024**3
 atomic_write(gen/'manifest.json',json.dumps(status,indent=2))
 for part in gen.glob('*.parquet'):sync_file(part)
 sync_directory(gen)
 link=ROOT/'lake/current.next';link.unlink(missing_ok=True);link.symlink_to(gen.name);os.replace(link,ROOT/'lake/current');sync_directory(ROOT/'lake');atomic_write(ROOT/'state/health.json',json.dumps(status,indent=2))
 # Generation cleanup requires an operator retention policy; never remove a reader's pinned snapshot here.
 return status

def scan():
 import fcntl
 with open(ROOT/'state/scan.lock','w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  c=db();reconcile_manifests(c);live_scan(c);local_scan(c);reconcile_manifests(c);s=publish(c);c.close();print(json.dumps(s),flush=True)

def export():
 import fcntl
 with open(ROOT/'state/publish.lock','w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  _export_locked()

def _export_locked():
 c=db();c.commit();c.execute('BEGIN')
 try:status=_publish(c)
 finally:c.commit();c.close()
 dest=ROOT/'export'/('slurm-history-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.tar.gz')
 temporary=dest.with_name('.'+dest.name+'.partial')
 with tarfile.open(temporary,'w:gz') as t:
  current=Path(status['generation'])
  for p in current.iterdir():t.add(p,arcname='tables/'+p.name)
  hashes=set(pq.read_table(current/'artifacts.parquet',columns=['stored_sha256']).column('stored_sha256').to_pylist())
  for sha in sorted(hashes):t.add(ROOT/'lake/payloads'/(sha+'.parquet'),arcname='payloads/'+sha+'.parquet')
  t.add(ROOT/'app/README.md',arcname='README.md')
 sync_file(temporary);os.replace(temporary,dest);sync_directory(dest.parent)
 hasher=hashlib.sha256()
 with open(dest,'rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):hasher.update(chunk)
 (dest.with_suffix(dest.suffix+'.sha256')).write_text(hasher.hexdigest()+'  '+dest.name+'\n');print(dest)
if __name__=='__main__':
 if len(sys.argv)>1 and sys.argv[1]=='export':export()
 else:scan()
