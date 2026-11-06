"""Fair bounded multi-job/cohort capture; strict SSH and configured path boundaries."""
import base64, json, os, shlex, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from history import ROOT,db,record,err,command,now
from settings import CONFIG,manifests,ssh_args
from durable import atomic_write

# Executed remotely; uses only the supplied paths and emits content bounded by a total-byte budget.
REMOTE=r'''
import os,sys,json,base64,pathlib
spec=json.loads(sys.argv[1]);allowed=[pathlib.Path(p).resolve() for p in spec['allowed']]
def permitted(p):
 p=pathlib.Path(p).resolve()
 return any(p==root or root in p.parents for root in allowed)
blocked=('credential','secret','token','id_rsa','id_ed25519','.pem','.key')
items=[];errors=[];seen=set()
def add(p,explicit=False):
 p=pathlib.Path(p)
 if str(p) in seen:return
 seen.add(str(p))
 if any(s in p.name.lower() for s in blocked):return
 try:
  if not permitted(p):errors.append({'path':str(p),'error':'outside approved remote roots'});return
  s=p.stat()
  if not p.is_file():return
  if s.st_size>spec['max_file']:errors.append({'path':str(p),'error':'oversized artifact deferred'});return
  items.append({'path':str(p),'size':s.st_size,'mtime':s.st_mtime})
 except Exception as e:errors.append({'path':str(p),'error':str(e)})
for p in spec['files']:add(p,True)
for root in spec['roots']:
 if not permitted(root):errors.append({'path':root,'error':'outside approved remote roots'});continue
 if not os.path.isdir(root):errors.append({'path':root,'error':'experiment directory missing'});continue
 for parent,dirs,files in os.walk(root,followlinks=False):
  dirs[:]=[d for d in dirs if d not in ['checkpoints','.git','datasets','weights','images'] and not any(s in d.lower() for s in blocked)]
  for n in files:
   if len(items)>=spec['max_files']:break
   if pathlib.Path(n).suffix in ['.out','.log','.err','.sh','.yaml','.yml','.json','.jsonl','.py','.txt','.md','.sbatch','.conf'] or n in ['_CONFIG','_TASKS','_VERSION','_DONE']:add(os.path.join(parent,n))
  if len(items)>=spec['max_files']:errors.append({'path':root,'error':'file inventory cap reached; split roots or raise reviewed budget'});break
sent=0;captured=0;deferred=0
for x in sorted(items,key=lambda x:x['path']):
 old=spec['known'].get(x['path'])
 if old and old==[x['size'],x['mtime']]:continue
 if sent+x['size']>spec['batch_bytes']:deferred+=1;continue
 try:
  with open(x['path'],'rb') as f:b=f.read(spec['max_file']+1)
  if len(b)>spec['max_file']:raise ValueError('file grew past maximum size')
  if sent+len(b)>spec['batch_bytes']:deferred+=1;continue
  # Stat changes during a read remain explicit and are revisited next pass.
  post=os.stat(x['path'])
  if post.st_size!=x['size'] or post.st_mtime!=x['mtime']:x['size']=len(b);x['mtime']=0
  sent+=len(b);captured+=1;x['data']=base64.b64encode(b).decode();print(json.dumps(x),flush=True)
 except Exception as e:errors.append({'path':x['path'],'error':str(e)})
for e in errors:print(json.dumps(e),flush=True)
print(json.dumps({'summary':{'inventory_count':len(items),'captured_count':captured,'deferred_count':deferred,'errors':len(errors),'bytes':sent}}),flush=True)
'''

def load_manifests():
    merged={}
    for p in manifests():
        try:
            x=json.loads(p.read_text());j=int(x['job_id']);merged[j]=dict(merged.get(j,{}),**x)
        except Exception as e:
            c=db();err(c,str(p),e);c.commit();c.close()
    c=db()
    for job in merged.values():
        row=c.execute('select metadata from jobs where job_id=?',(int(job['job_id']),)).fetchone()
        if row:
            metadata=json.loads(row[0]);job['completion']=metadata.get('completion',{})
    c.close()
    return list(merged.values())

def capture_host(job,host):
    c=db();ident=int(job['job_id']);roots=job.get('experiments',[])
    if job.get('experiment'):roots=[job['experiment']]+roots
    files=[]
    if host==job.get('batch_host'):
        files=[p for p in [job.get('stdout'),job.get('stderr'),job.get('log_path')] if isinstance(p,str) and p.startswith('/')]
    known={r[0].removeprefix('ssh://'+host):[r[1],r[2]] for r in c.execute('select source,size,mtime from files where job_id=? and source like ?',(ident,'ssh://'+host+'/%'))}
    spec={'roots':list(dict.fromkeys(roots)),'files':list(dict.fromkeys(files)),'allowed':CONFIG['remote_allowed_roots'],
          'known':known,'max_file':64*1024*1024,'max_files':int(CONFIG.get('max_remote_files',2000)),
          'batch_bytes':int(CONFIG.get('max_remote_batch_bytes',32*1024*1024))}
    summary={};problems=[]
    try:
        output=command(ssh_args(host)+['nice -n 19 python3 -c '+shlex.quote(REMOTE)+' '+shlex.quote(json.dumps(spec))],int(CONFIG.get('remote_capture_timeout_seconds',120)))
        for line in output.splitlines():
            x=json.loads(line)
            if 'summary' in x:summary=x['summary'];continue
            src='ssh://'+host+x['path']
            if 'error' in x:err(c,src,x['error']);problems.append(x['error']);continue
            record(c,src,base64.b64decode(x['data']),x['size'],x['mtime'],ident);c.commit()
        if not summary:raise RuntimeError('remote command produced no completeness summary')
        status='partial' if problems or summary.get('deferred_count') or not (roots or files) else 'inventoried'
        if summary.get('deferred_count'):problems.append('Byte budget deferred '+str(summary['deferred_count'])+' files; revisit required')
        if not (roots or files):problems.append('No configured artifact paths for this job/host; metadata capture alone')
        c.execute('update errors set resolved_utc=? where source=? and resolved_utc is null',(now(),f'remote/job{ident}/{host}'))
    except Exception as exc:
        status='error';problems.append(str(exc));err(c,f'remote/job{ident}/{host}',exc)
    c.execute('insert or replace into remote_coverage values(?,?,?,?,?,?,?)',(ident,host,summary.get('inventory_count',0),summary.get('captured_count',0),status,now(),'; '.join(problems)[:2000]));c.commit();c.close()

def run(historical=False):
    if not CONFIG.get('remote_capture_enabled',False):
        name='historical-health' if historical else 'live-health'
        atomic_write(ROOT/'state'/(name+'.json'),json.dumps({'updated_utc':now(),'status':'remote capture disabled; approved local/shared sources only'}));return
    checkpoint=ROOT/'state'/('remote-backfill.json' if historical else 'live-queue.json')
    state=json.loads(checkpoint.read_text()) if checkpoint.exists() else {'last_attempt':{}}
    jobs=load_manifests()
    terminal={'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'}
    jobs=[j for j in jobs if (j.get('final_state') in terminal or j.get('slurm',{}).get('JobState') in terminal or j.get('completion',{}).get('JobState') in terminal)==historical]
    candidates=[]
    for job in jobs:
        nodes=list(dict.fromkeys(job.get('nodes',[])))
        if not nodes and job.get('batch_host') not in [None,'(null)']:nodes=[job['batch_host']]
        cap=int(CONFIG.get('remote_manifest_limit',128))
        if len(nodes)>cap:
            c=db();err(c,f'job{job["job_id"]}/cohort','Host cap reached; configure reviewed fleet scope');c.commit();c.close()
        for host in nodes[:cap]:
            key=str(job['job_id'])+'/'+host
            candidates.append((state['last_attempt'].get(key,''),key,job,host))
    candidates.sort(key=lambda row:(row[0],row[1]))
    budget=int(CONFIG.get('max_remote_hosts_per_pass',8))
    selected=candidates[:budget]
    # Two concurrent remote reads maximum; total hosts bounded independently of fleet size.
    def capture(item):
        _,key,job,host=item;capture_host(job,host);return key
    with ThreadPoolExecutor(max_workers=2) as pool:
        for key in pool.map(capture,selected):
            state['last_attempt'][key]=now();state['updated_utc']=now()
            atomic_write(checkpoint,json.dumps(state,indent=2))
    name='historical-health' if historical else 'live-health'
    atomic_write(ROOT/'state'/(name+'.json'),json.dumps({'updated_utc':now(),'eligible_jobs':len(jobs),'eligible_hosts':len(candidates),'selected_hosts':len(selected),'deferred_hosts':max(0,len(candidates)-len(selected))}))
if __name__=='__main__':run()
