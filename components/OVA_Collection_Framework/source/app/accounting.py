"""Retained accounting with a durable overlapping cursor and bounded history windows."""
import datetime as dt,json
from history import ROOT,SLURM,db,command,record,err,now
from settings import CONFIG
from durable import atomic_write

def collect():
    if not CONFIG.get('accounting_enabled',False):return
    checkpoint=ROOT/'state/accounting-cursor.json'
    saved=json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    current=dt.datetime.now(dt.timezone.utc)
    if saved and (current-dt.datetime.fromisoformat(saved['polled_utc'])).total_seconds()<int(CONFIG.get('accounting_poll_seconds',300)):return
    baseline=current-dt.timedelta(hours=int(CONFIG.get('accounting_lookback_hours',48)))
    if saved:start=dt.datetime.fromisoformat(saved['through_utc'])-dt.timedelta(minutes=2)
    elif CONFIG.get('accounting_start_utc'):start=dt.datetime.fromisoformat(CONFIG['accounting_start_utc'])
    else:start=baseline
    end=min(current,start+dt.timedelta(hours=24))
    args=[SLURM+'sacct','--json','--allusers','--starttime',start.strftime('%Y-%m-%dT%H:%M:%S'),'--endtime',end.strftime('%Y-%m-%dT%H:%M:%S')]
    c=db()
    try:
        b=command(args,60);x=json.loads(b);source='slurm://accounting/'+end.strftime('%Y%m%dT%H%M%SZ');record(c,source,b)
        supported=True
        for job in x.get('jobs',[]):
            ident=job.get('job_id')
            if type(ident) is not int:supported=False;err(c,source,'Unsupported accounting job_id shape; raw response preserved');continue
            record(c,f'slurm://job{ident}/accounting.json',json.dumps(job).encode(),job=ident)
            row=c.execute('select metadata,coverage from jobs where job_id=?',(ident,)).fetchone();metadata=json.loads(row[0]) if row else {};metadata['accounting']=job
            c.execute('insert or replace into jobs values(?,?,?,?)',(ident,json.dumps(metadata),row[1] if row else 'accounting_and_artifacts',now()))
        if supported:
            c.execute('update errors set resolved_utc=? where source=? and resolved_utc is null',(now(),'slurm/accounting'));c.commit()
            atomic_write(checkpoint,json.dumps({'through_utc':end.isoformat(),'polled_utc':current.isoformat()}))
    except Exception as exc:err(c,'slurm/accounting',exc)
    c.commit();c.close()
if __name__=='__main__':collect()
