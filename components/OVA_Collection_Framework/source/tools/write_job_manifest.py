#!/usr/bin/env python3
"""Register artifact paths from an actual scheduler/runner identity; no scheduler mutations."""
import argparse,json,os,fcntl,sys
sys.path.insert(0,str(__import__("pathlib").Path(__file__).resolve().parents[1]/"app"))
from durable import atomic_write
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--input',type=Path,required=True);a=p.parse_args();cfg=json.loads(a.config.read_text());x=json.loads(a.input.read_text())
if not isinstance(x.get('job_id'),int) or x['job_id']<1:raise SystemExit('Actual numeric Slurm job_id required')
if not isinstance(x.get('nodes'),list):raise SystemExit('Explicit node array required; expand using scontrol show hostnames')
# A dedicated trusted manifest directory can be configured after the discovered directory.
directory=Path(cfg['manifest_dirs'][-1]);directory.mkdir(parents=True,exist_ok=True);p=directory/f'job{x["job_id"]}.json'
with (directory/'.registration.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 if p.exists():old=json.loads(p.read_text());old.update(x);x=old
 x['cluster']=cfg['cluster'];x['cluster_epoch']=cfg['epoch'];atomic_write(p,json.dumps(x,indent=2)+'\n');print(p)
