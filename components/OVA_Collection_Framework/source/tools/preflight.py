#!/usr/bin/env python3
"""Read-only target source checks, intended to run as the collection identity."""
import argparse,json,os,subprocess
from pathlib import Path
from configuration import load
p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args();c=load(a.config);checks=[]
def check(label,ok,detail):checks.append({'check':label,'ok':bool(ok),'detail':detail})
for label in ['controller_log','browser_auth_file']:
    path=Path(c[label]);check(label,path.is_file() and os.access(path,os.R_OK),'Readable exact source required')
check('terminal_feed',Path(c['completion_log']).is_file() and os.access(c['completion_log'],os.R_OK) or c['accounting_enabled'],'Durable completion log or verified accounting required')
if c['remote_capture_enabled']:
    for key in ['ssh_known_hosts','ssh_identity_file']:
        check(key,Path(c[key]).is_file() and os.access(c[key],os.R_OK),'Remote capture requires readable provisioned SSH trust/identity')
for path in c['local_roots']:check('local_root',Path(path).is_dir() and os.access(path,os.R_OK|os.X_OK),'Approved source root exists and is readable')
for path in c['manifest_dirs']:check('manifest_directory',Path(path).is_dir() and os.access(path,os.W_OK|os.X_OK),'Trusted manifest directory writable')
try:
    result=subprocess.run([str(Path(c['slurm_bin'])/'scontrol'),'show','jobs','-o'],capture_output=True,timeout=25,check=True)
    check('slurm_visibility',True,'Command accepted; verify all-user visibility against an independent inventory')
except (OSError,subprocess.SubprocessError):check('slurm_visibility',False,'scontrol show jobs failed; inspect target permissions')
if c['accounting_enabled']:
    try:
        subprocess.run([str(Path(c['slurm_bin'])/'sacct'),'--json','--allusers','--starttime','now-1hours'],capture_output=True,timeout=60,check=True)
        check('accounting',True,'JSON query accepted; commissioning must verify supported scalar IDs and step coverage')
    except (OSError,subprocess.SubprocessError):check('accounting',False,'Configured sacct adapter unavailable')
result={'status':'PREFLIGHT_PASS' if all(x['ok'] for x in checks) else 'PREFLIGHT_FAIL','checks':checks,'coverage_proven':False};print(json.dumps(result,indent=2));raise SystemExit(0 if result['status']=='PREFLIGHT_PASS' else 1)
