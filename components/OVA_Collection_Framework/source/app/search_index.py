"""Incremental full-text acceleration over immutable raw payloads; safely resumes."""
import sqlite3,gzip,time,json,os
from history import ROOT,db,now
c=db();s=sqlite3.connect(ROOT/'state/search.sqlite',timeout=30);s.execute('pragma journal_mode=WAL');s.execute('create virtual table if not exists chunks using fts5(sha UNINDEXED,part UNINDEXED,text)');s.execute('create table if not exists indexed(sha text primary key,bytes integer,utc text)');done={r[0] for r in s.execute('select sha from indexed')};todo=[(r[0],r[1]) for r in c.execute("select stored_sha256,max(stored_bytes) from artifacts group by stored_sha256 order by min(case when source like '%/log-%' then 0 when source like '%.json' or source like '%.yaml' then 1 else 2 end),max(job_id) desc") if r[0] not in done];total=len(todo)+len(done);started=time.monotonic()
for sha,size in todo:
 if time.monotonic()-started>45:break
 s.execute('delete from chunks where sha=?',(sha,));p=ROOT/'raw'/sha[:2]/(sha+'.gz')
 try:
  with gzip.open(p,'rb') as f:
   part=0;tail=''
   while True:
    b=f.read(65536)
    if not b:break
    text=b.decode('utf-8','replace');s.execute('insert into chunks values(?,?,?)',(sha,part,tail+text));tail=text[-512:];part+=1
  s.execute('insert into indexed values(?,?,?)',(sha,size,now()));s.commit()
 except Exception:s.rollback()
status={'updated_utc':now(),'indexed_payloads':s.execute('select count(*) from indexed').fetchone()[0],'available_payloads':total};p=ROOT/'state/search-health.tmp';p.write_text(json.dumps(status));os.replace(p,ROOT/'state/search-health.json');s.close();c.close()
