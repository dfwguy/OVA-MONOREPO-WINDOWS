from history import *
c=db()
for source,sha,size,mtime in c.execute("select f.source,a.stored_sha256,f.size,f.mtime from files f join artifacts a on f.version=a.version where (f.source like '%.log' or f.source like '%.out' or f.source like '%.err') and f.source not like '%/nccl-%'").fetchall():
 b=gzip.decompress((ROOT/'raw'/sha[:2]/(sha+'.gz')).read_bytes());j=c.execute('select job_id from files where source=?',(source,)).fetchone()[0];record(c,source,b,size,mtime,j,force=True);c.commit()
c.commit();c.close()
