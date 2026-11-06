import os,json,gzip,re,base64,http.client,time,threading,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from http.cookies import SimpleCookie
from flask import Flask,request,jsonify,Response,send_file,session,redirect
from waitress import serve
import duckdb
from history import ROOT
app=Flask(__name__)
from settings import CONFIG
import hashlib, hmac
try:app.secret_key=hashlib.sha256(Path(CONFIG['browser_auth_file']).read_bytes()).digest()
except OSError:app.secret_key=os.urandom(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Strict',SESSION_COOKIE_SECURE=bool(CONFIG.get('browser_secure_cookie',False)),MAX_CONTENT_LENGTH=4096)
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  try:expected=Path(CONFIG['browser_auth_file']).read_text().strip()
  except OSError:return 'Browser credential unavailable',503
  if len(expected)>=32 and hmac.compare_digest(request.form.get('token',''),expected):
   session.clear();session['credential']=hashlib.sha256(expected.encode()).hexdigest();return redirect('/')
  return 'Invalid access token',401
 return Response('<!doctype html><title>OVA Collection Framework | NVIDIA</title><style>body{font:18px system-ui;background:#101010;color:white;padding:8vw}h1{border-left:6px solid #76b900;padding-left:20px}input,button{padding:12px;margin:10px}button{background:#76b900}</style><h1>NVIDIA · OVA Collection Framework</h1><p>Sign in to the cluster evidence browser.</p><form method="post"><label>Access token <input name="token" type="password" required autocomplete="off"></label><button>Sign in</button></form>',mimetype='text/html')

def authorized():
 import hmac
 from settings import CONFIG
 try:
  expected=Path(CONFIG['browser_auth_file']).read_text().strip()
  return len(expected)>=32 and (hmac.compare_digest(request.headers.get('X-Evidence-Token',''),expected) or hmac.compare_digest(session.get('credential',''),hashlib.sha256(expected.encode()).hexdigest()))
 except (OSError,KeyError):return False
@app.before_request
def auth():
 if request.path=='/login':return None
 if not authorized():
  if request.path=='/':return redirect('/login')
  return jsonify(error='Authentication required.'),401
@app.after_request
def headers(r):r.headers['Cache-Control']='no-store';r.headers['X-Content-Type-Options']='nosniff';return r
def conn():
 c=duckdb.connect();c.execute("SET memory_limit='256MB'");c.execute('SET threads=1');gen=(ROOT/'lake/current').resolve()
 for t in ['jobs','artifacts','metrics','metric_observations','remote_coverage','validations','errors','gaps']:c.execute(f"create table {t} as select * from read_parquet('{gen}/{t}.parquet')")
 c.execute("SET enable_external_access=false");c.execute("SET memory_limit='256MB'");c.execute('SET threads=1');return c
@app.get('/api/health')
def health():
 p=ROOT/'state/health.json';x=json.loads(p.read_text()) if p.exists() else {'status':'Initial backfill underway'}
 for label,name in [('metadata','metadata-health.json'),('live_artifacts','live-health.json')]:
  q=ROOT/'state'/name
  if q.exists():
   v=json.loads(q.read_text());x[label]=v;x[label+'_lag_seconds']=round((datetime.now(timezone.utc)-datetime.fromisoformat(v['updated_utc'])).total_seconds())
 x['remote_backfill']=json.loads((ROOT/'state/remote-backfill.json').read_text()) if (ROOT/'state/remote-backfill.json').exists() else {'status':'Initial queue pending'}
 if x.get('updated_utc'):x['published_lag_seconds']=round((datetime.now(timezone.utc)-datetime.fromisoformat(x['updated_utc'])).total_seconds())
 x['full_text_search']=json.loads((ROOT/'state/search-health.json').read_text()) if (ROOT/'state/search-health.json').exists() else {'status':'Initial text indexing underway'}
 return jsonify(x)
@app.get('/api/query')
def query():
 sql=request.args.get('sql','select job_id, workload, dtype, gpus, state, coverage from jobs order by job_id desc');
 if len(sql)>10000 or not re.match(r'^\s*(select|with)\b',sql,re.I) or ';' in sql:return jsonify(error='Enter one read-only SELECT query.'),400
 c=conn();timer=threading.Timer(10,c.interrupt);timer.start()
 try:
  result=c.execute('select * from ('+sql+') as q limit 1000');return jsonify(columns=[x[0] for x in result.description],rows=result.fetchall())
 except Exception as e:return jsonify(error=str(e)),400
 finally:timer.cancel();c.close()
@app.get('/api/search')
def search():
 q=request.args.get('q','');j=request.args.get('job_id',type=int);c=conn();rows=c.execute('select version,job_id,source,stored_sha256,redacted from artifacts where (? is null or job_id=?) qualify row_number() over(partition by source order by captured_utc desc)=1 order by captured_utc desc',[j,j]).fetchall();out=[]
 if q and (ROOT/'state/search.sqlite').exists():
  ss=sqlite3.connect('file:'+str(ROOT/'state/search.sqlite')+'?mode=ro',uri=True,timeout=10)
  try:
   needle='"'+q.replace('"','""')+'"';shas=list({r[3] for r in rows});hits=ss.execute('select sha,text from chunks where chunks match ?'+(' and sha in ('+','.join('?' for _ in shas)+')' if j is not None and shas else '')+' limit 1000',[needle]+(shas if j is not None and shas else [])).fetchall();indexed={r[0] for r in ss.execute('select sha from indexed')};bysha={}
   for row in rows:bysha.setdefault(row[3],row)
   results=[];seen=set()
   for sha,text in hits:
    if sha in bysha and sha not in seen:
     v,j,src,sha,red=bysha[sha];results.append({'version':v,'job_id':j,'source':src,'redacted':red,'match':text[max(0,text.lower().find(q.lower())-100):][:1000]});seen.add(sha)
     if len(results)>=100:break
   for v,j,src,sha,red in rows:
    if q.lower() in src.lower() and sha not in seen:results.append({'version':v,'job_id':j,'source':src,'redacted':red,'match':'path'});seen.add(sha)
    if len(results)>=100:break
   covered=set(indexed);fallback_started=time.monotonic();fallback_bytes=0
   for v,j,src,sha,red in sorted(rows,key=lambda r:0 if '/log-' in r[2] else 1):
    if sha in covered or sha in seen:continue
    if time.monotonic()-fallback_started>10 or fallback_bytes>128*1024*1024 or len(results)>=100:break
    p=ROOT/'raw'/sha[:2]/(sha+'.gz');needle_bytes=q.lower().encode();tail=b'';complete=True
    with gzip.open(p,'rb') as f:
     while True:
      chunk=f.read(65536)
      if not chunk:break
      fallback_bytes+=len(chunk);buf=tail+chunk;where=buf.lower().find(needle_bytes)
      if where>=0:results.append({'version':v,'job_id':j,'source':src,'redacted':red,'match':buf[max(0,where-100):where+600].decode('utf-8','replace')});seen.add(sha);break
      tail=buf[-max(len(needle_bytes)-1,0):] if len(needle_bytes)>1 else b''
      if time.monotonic()-fallback_started>10 or fallback_bytes>128*1024*1024:complete=False;break
    if complete:covered.add(sha)
   ready=sum(1 for r in rows if r[3] in covered);c.close();ss.close();return jsonify(results=results,available_artifacts=len(rows),searched_artifacts=ready,result_limit=100,truncated=ready<len(rows) or len(results)>=100,scope='Indexed word/phrase search plus bounded literal search during warmup. Limit100matches; partial coverage is reported.')
  except Exception:ss.close()
 started=time.monotonic();searched=0;read_bytes=0;truncated=False
 for v,j,src,sha,red in rows:
  if time.monotonic()-started>20 or read_bytes>512*1024*1024 or len(out)>=100:truncated=True;break
  searched+=1
  if not q or q.lower() in src.lower():out.append({'version':v,'job_id':j,'source':src,'redacted':red,'match':'path'});continue
  p=ROOT/'raw'/sha[:2]/(sha+'.gz');needle=q.lower().encode();tail=b'';offset=0
  with gzip.open(p,'rb') as f:
   while True:
    chunk=f.read(65536)
    if not chunk:break
    read_bytes+=len(chunk);buf=tail+chunk;where=buf.lower().find(needle)
    if where>=0:
     out.append({'version':v,'job_id':j,'source':src,'redacted':red,'byte_offset':max(0,offset-len(tail)+where),'match':buf[max(0,where-100):where+600].decode('utf-8','replace')});break
    tail=buf[-max(len(needle)-1,0):] if len(needle)>1 else b'';offset+=len(chunk)
    if time.monotonic()-started>20 or read_bytes>512*1024*1024:truncated=True;break
 c.close();return jsonify(results=out,available_artifacts=len(rows),searched_artifacts=searched,result_limit=100,truncated=truncated,bytes_searched=read_bytes,scope='Latest snapshots;100 matches/20seconds/512MiB per request. Use job ID to narrow incomplete searches.')
@app.get('/api/artifact/<version>')
def artifact(version):
 if not re.fullmatch('[a-f0-9]{64}',version):return '',404
 c=conn();row=c.execute('select source,stored_sha256 from artifacts where version=?',[version]).fetchone();c.close()
 if not row:return '',404
 p=ROOT/'raw'/row[1][:2]/(row[1]+'.gz')
 def chunks():
  with gzip.open(p,'rb') as f:
   while True:
    b=f.read(65536)
    if not b:break
    yield b
 return Response(chunks(),mimetype='application/octet-stream',headers={'Content-Disposition':'attachment; filename="'+Path(row[0]).name.replace('"','')+'"'})
@app.get('/api/exports')
def exports():return jsonify(files=[p.name for p in sorted((ROOT/'export').glob('*.tar.gz'))])
@app.get('/api/export/<name>')
def download(name):
 if not re.fullmatch(r'slurm-history-\d{8}T\d{6}\.tar\.gz',name):return '',404
 return send_file(ROOT/'export'/name,as_attachment=True)
@app.get('/')
def index():return Response('''<!doctype html><html><head><meta charset="utf-8"><title>OVA Collection Framework | NVIDIA</title><style>body{font:15px system-ui;background:#101010;color:#e8eff8;margin:0}main{max-width:1300px;margin:auto;padding:28px}h1{font-size:26px}input,textarea,button{font:inherit;background:#1e293b;color:#edf5ff;border:1px solid #526176;border-radius:5px;padding:10px}textarea{width:97%;height:86px}button{cursor:pointer}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid #334155;padding:9px;text-align:left;vertical-align:top;max-width:550px;overflow-wrap:anywhere}pre{white-space:pre-wrap}a{color:#76b900}.muted{color:#bac7d8}#status{padding:16px;background:#1a2537;border-radius:8px}</style></head><body><main><p style="color:#76b900;letter-spacing:3px;font-weight:700">NVIDIA</p><h1>OVA Collection Framework</h1><p class="muted">Job history, raw logs, configurations, validation evidence and performance measurements.</p><div id="status">Loading collection status…</div><h2>Search logs and artifacts</h2><input id="job" type="number" placeholder="Job ID (optional)"><input id="term" placeholder="Error, node, model or text"><button onclick="search()">Search</button><h2>Explore tables</h2><p>Available tables: jobs, artifacts, metrics, gaps, errors. Results are limited to 1,000 rows.</p><textarea id="sql">SELECT job_id, workload, dtype, gpus, state, coverage FROM jobs ORDER BY job_id DESC</textarea><p><button onclick="query()">Run query</button> <button onclick="preset('metrics')">Measurements</button> <button onclick="preset('gaps')">Missing history</button> <button onclick="preset('errors')">Collection errors</button> <button onclick="exports()">Exports</button></p><div id="result"></div></main><script>const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));async function get(p){const r=await fetch(p);return r.json()}function table(cols,rows){document.getElementById('result').innerHTML='<table><thead><tr>'+cols.map(c=>'<th>'+esc(c)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+esc(typeof v==='object'?JSON.stringify(v):v)+'</td>').join('')+'</tr>').join('')+'</tbody></table>'}async function query(){const x=await get('api/query?sql='+encodeURIComponent(document.getElementById('sql').value));if(x.error){document.getElementById('result').textContent=x.error;return}table(x.columns,x.rows)}function preset(t){document.getElementById('sql').value=t==='metrics'?'SELECT job_id, iteration, metric, value, unit, artifact_id FROM metrics ORDER BY job_id DESC, iteration DESC':t==='errors'?'SELECT * FROM errors ORDER BY id DESC':'SELECT * FROM gaps';query()}async function search(){const x=await get('api/search?q='+encodeURIComponent(document.getElementById('term').value)+'&job_id='+document.getElementById('job').value);document.getElementById('result').innerHTML='<p>'+x.searched_artifacts+' of '+x.available_artifacts+' current artifacts searched'+(x.truncated?' (partial; narrow by Job ID)':'')+'. '+esc(x.scope)+'</p>'+x.results.map(r=>'<p><a href="api/artifact/'+r.version+'">Job '+r.job_id+' · '+esc(r.source)+'</a><br>'+esc(r.match)+'</p>').join('')}async function exports(){const x=await get('api/exports');document.getElementById('result').innerHTML=x.files.map(n=>'<p><a href="api/export/'+n+'">'+esc(n)+'</a></p>').join('')}async function health(){const x=await get('api/health');document.getElementById('status').textContent=x.job_count===undefined?'Initial backfill underway':'Collected '+x.job_count+' jobs through job '+x.max_job_id+' · '+x.artifact_versions+' artifact versions · '+x.metrics+' measurements · '+x.missing_job_ids.length+' history gaps · '+x.error_count+' collection errors · Updated '+x.updated_utc}health();query();setInterval(health,15000)</script></body></html>''',mimetype='text/html')
if __name__=='__main__':
 from settings import CONFIG
 serve(app,host='127.0.0.1',port=int(CONFIG['browser_port']),threads=4)
