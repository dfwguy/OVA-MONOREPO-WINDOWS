from history import *
c=db();c.execute('create table if not exists validation_seen(artifact_id text primary key)')
for v,j,source,sha in c.execute("select version,job_id,source,stored_sha256 from artifacts where version in(select version from files) and source like '%.json' and version not in(select artifact_id from validation_seen)").fetchall():
 try:
  b=gzip.decompress((ROOT/'raw'/sha[:2]/(sha+'.gz')).read_bytes());x=json.loads(b)
  if isinstance(x,dict):
   if not j and isinstance(x.get('job_id'),int):j=x['job_id'];c.execute('update artifacts set job_id=? where version=?',(j,v));c.execute('update files set job_id=? where version=?',(j,v))
   summary={k:x[k] for k in ['passed','pass','ok','ready','failures','errors','runtime_gate','runtime_gate_failure','validation_status','qualification_status','all_rail_validation','final_state','exit_code'] if k in x}
   if summary:
    status='PASS' if x.get('passed') is True or x.get('ok') is True else 'FAIL' if x.get('passed') is False or x.get('ok') is False else 'EVIDENCE';c.execute('insert or replace into validations values(?,?,?,?,?)',(v,j,source,status,json.dumps(summary)))
  c.execute('insert or ignore into validation_seen values(?)',(v,));c.commit()
 except Exception as e:err(c,source,e);c.commit()
c.close()
