"""Deployment input checks. Customer settings live outside the repository."""
import json, re
from pathlib import Path

IDENTIFIER = re.compile(r'[A-Za-z0-9_-]+')

def load(path):
    config = json.loads(Path(path).read_text())
    for key in ('root','slurm_bin','controller_log','completion_log','ssh_known_hosts','ssh_identity_file','browser_auth_file'):
        value = config.get(key)
        if not isinstance(value,str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', value) or '..' in Path(value).parts:
            raise ValueError('Invalid absolute path: '+key)
    root = Path(config['root'])
    if len(root.parts)<6 or root.parts[:3] != ('/','var','lib') or root.parts[3]!='slurm-evidence':
        raise ValueError('root must be a dedicated /var/lib/slurm-evidence/<cluster>/<epoch> directory')
    for key in ('site','cluster','epoch','service_user','service_group'):
        if not isinstance(config.get(key),str) or not IDENTIFIER.fullmatch(config[key]):
            raise ValueError('Invalid identifier: '+key)
    if config['service_user']=='root' or config['service_group']=='root':
        raise ValueError('Collector must use a dedicated non-root identity')
    for key in ('manifest_dirs','local_roots','remote_allowed_roots'):
        paths = config.get(key)
        if not isinstance(paths,list) or not paths:
            raise ValueError('Explicit non-empty path list required: '+key)
        for value in paths:
            if not isinstance(value,str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+',value) or '..' in Path(value).parts or value in ('/','/etc','/var','/home','/root','/tmp','/scratch','/srv'):
                raise ValueError('Use narrow approved roots: '+key)
    if any(not Path(x).is_relative_to(root/'state') for x in config['manifest_dirs']):
        raise ValueError('Manifest directories must be beneath root/state')
    for key,low,high in [('browser_port',1024,65535),('first_job_id',1,2147483647),('max_gap_span',1,1000000),('max_jobs_per_live_pass',1,32),('remote_manifest_limit',1,512),('remote_capture_timeout_seconds',1,120),('max_remote_files',1,10000),('max_remote_batch_bytes',1048576,33554432),('accounting_lookback_hours',1,168),('accounting_poll_seconds',60,3600),('max_remote_hosts_per_pass',1,16),('local_stream_timeout_seconds',1,300),('local_stream_threshold_bytes',1048576,268435456)]:
        v=config.get(key)
        if type(v) is not int or not low<=v<=high:raise ValueError('Invalid bounded setting: '+key)
    if not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service',config.get('slurm_service','')):
        raise ValueError('Invalid Slurm service')
    for flag in ['accounting_enabled','remote_capture_enabled','browser_secure_cookie']:
        if not isinstance(config.get(flag),bool):raise ValueError(flag+' must be boolean')
    for key in ('metadata','live','publication','search'):
        v=config.get('freshness_budget_seconds',{}).get(key)
        if type(v) is not int or not 30<=v<=86400:raise ValueError('Invalid freshness budget: '+key)
    if any('example' in config[k] or 'REPLACE' in config[k] for k in ('site','cluster','epoch')):
        raise ValueError('Replace example cluster identity before deployment')
    return config
