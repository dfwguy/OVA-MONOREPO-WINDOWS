"""Fast scheduler metadata/script capture and durable generic job discovery."""
import json, os, re
from pathlib import Path
from history import db, live_scan, reconcile_manifests, command, SLURM, ROOT, now, err, record
from settings import CONFIG
from durable import atomic_write

def discover(c):
    output=command([SLURM+'scontrol','show','jobs','-o']).decode('utf-8','replace')
    dest=ROOT/'state/job-manifests';dest.mkdir(parents=True,exist_ok=True)
    for line in output.splitlines():
        fields=dict(re.findall(r'(\w+)=([^\s]+)',line)); ident=fields.get('JobId','')
        if not ident.isdecimal():
            err(c,'discovery/job-id','Unsupported job identity: '+ident);continue
        job=int(ident);p=dest/f'job{job}.json';old=json.loads(p.read_text()) if p.exists() else {}
        nodes=old.get('nodes',[])
        expression=fields.get('NodeList','')
        if expression and expression not in ['(null)','None']:
            try:nodes=command([SLURM+'scontrol','show','hostnames',expression]).decode().splitlines()
            except Exception as exc:err(c,f'discovery/job{job}/nodes',exc)
        # Never recurse the user's entire WorkDir. Explicit run templates or trusted manifests supply roots.
        roots=[t.format(job_id=job) for t in CONFIG.get('experiment_templates',[])]
        x=dict(old,job_id=job,workload=fields.get('JobName',''),nodes=nodes,
               batch_host=fields.get('BatchHost'),stdout=fields.get('StdOut'),stderr=fields.get('StdErr'),
               slurm=fields,discovered_utc=old.get('discovered_utc',now()),last_seen_utc=now(),
               cluster=CONFIG['cluster'],cluster_epoch=CONFIG['epoch'])
        if roots and not x.get('experiment'):x['experiments']=roots
        atomic_write(p,json.dumps(x,indent=2)+'\n')
        record(c,str(p),p.read_bytes(),job=job)
    c.commit()

def main():
    c=db();discover(c);reconcile_manifests(c);live_scan(c,capture_stdout=False);c.commit();c.close()
    from accounting import collect
    collect()
    atomic_write(ROOT/'state/metadata-health.json',json.dumps({'updated_utc':now()}))
if __name__=='__main__':main()
