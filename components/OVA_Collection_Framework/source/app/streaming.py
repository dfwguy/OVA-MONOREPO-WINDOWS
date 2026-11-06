"""Bounded-memory stable-file capture and incremental Parquet payload publication."""
import gzip,hashlib,os,tempfile,time
from pathlib import Path
from durable import sync_directory,sync_file

def capture(c,path,job=None):
    # Import lazily: history owns the common journal schema and redaction policy.
    from history import ROOT,CONFIG,redact,now,jid,kind,err
    path=Path(path);before=path.stat();started=time.monotonic();original=hashlib.sha256();stored=hashlib.sha256();redactions=0;stored_bytes=0
    fd,name=tempfile.mkstemp(prefix='.stream-',dir=ROOT/'raw');os.close(fd)
    try:
        with path.open('rb') as source,open(name,'wb') as output:
            with gzip.GzipFile(fileobj=output,mode='wb',mtime=0) as compressed:
                while True:
                    # Most log records are short lines. Bounded long/binary records may split.
                    block=source.readline(1048576)
                    if not block:break
                    if time.monotonic()-started>int(CONFIG.get('local_stream_timeout_seconds',120)):
                        raise TimeoutError('Large source capture exceeded pass budget; original retained, capture incomplete')
                    original.update(block);clean,count=redact(block);redactions+=count;stored.update(clean);stored_bytes+=len(clean);compressed.write(clean)
            output.flush();os.fsync(output.fileno())
        after=path.stat()
        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
            raise RuntimeError('Large source changed during capture; stable final version required')
        sha=original.hexdigest();saved=stored.hexdigest();target=ROOT/'raw'/saved[:2]/(saved+'.gz');target.parent.mkdir(exist_ok=True)
        if not target.exists():os.replace(name,target);sync_directory(target.parent)
        source=str(path);ident=jid(source) if job is None else job;version=hashlib.sha256((source+'\0'+sha).encode()).hexdigest()
        c.execute('insert or ignore into artifacts values(?,?,?,?,?,?,?,?,?,?,?)',(version,ident,source,sha,saved,before.st_size,stored_bytes,now(),int(redactions>0),'streamed/binary-preserved/redacted' if redactions else 'streamed/binary-preserved',kind(source)))
        c.execute('insert or replace into files values(?,?,?,?,?,?)',(source,before.st_size,before.st_mtime,sha,version,ident))
        if ident:c.execute('insert or ignore into jobs values(?,?,?,?)',(ident,'{}','artifacts_only',now()))
        c.execute('update errors set resolved_utc=? where source=? and resolved_utc is null',(now(),source));c.commit()
        return version
    finally:Path(name).unlink(missing_ok=True)

def publish_payload(raw,path,sha):
    import pyarrow as pa,pyarrow.parquet as pq
    schema=pa.schema([('stored_sha256',pa.string()),('chunk',pa.int64()),('byte_offset',pa.int64()),('data',pa.binary())])
    temporary=Path(path).with_suffix('.tmp');offset=0;chunk=0
    try:
        with gzip.open(raw,'rb') as source,pq.ParquetWriter(temporary,schema,compression='zstd') as writer:
            while True:
                data=source.read(1048576)
                if not data:break
                writer.write_table(pa.Table.from_pylist([{'stored_sha256':sha,'chunk':chunk,'byte_offset':offset,'data':data}],schema=schema));chunk+=1;offset+=len(data)
        sync_file(temporary);os.replace(temporary,path);sync_directory(Path(path).parent)
    finally:temporary.unlink(missing_ok=True)
