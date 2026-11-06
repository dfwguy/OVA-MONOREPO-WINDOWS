"""Explicit per-cluster settings; no secret values in JSON configuration."""
import json, os
from pathlib import Path
CONFIG_PATH=Path(os.environ.get('SLURM_HISTORY_CONFIG','/etc/slurm-evidence/cluster.json'))
CONFIG=json.loads(CONFIG_PATH.read_text())
required=['root','cluster','site','epoch','slurm_bin','manifest_dirs','local_roots','remote_allowed_roots','controller_log','completion_log','service_user','service_group','browser_port','browser_auth_file']
missing=[k for k in required if k not in CONFIG]
if missing: raise ValueError('Missing config keys: '+', '.join(missing))
ROOT_PATH=Path(os.environ.get('SLURM_HISTORY_ROOT',CONFIG['root']))
MANIFEST_DIRS=[Path(p) for p in CONFIG['manifest_dirs']]
CONTROLLER_LOG=Path(CONFIG['controller_log']); COMPLETION_LOG=Path(CONFIG['completion_log'])
LOCAL_ROOTS=[Path(p) for p in CONFIG['local_roots']]
FIRST_JOB_ID=int(CONFIG.get('first_job_id',1)); MAX_GAP_SPAN=int(CONFIG.get('max_gap_span',1000000))
def ssh_args(host):
 if not host or host.startswith('-') or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-' for c in host):raise ValueError('Invalid SSH hostname')
 args=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes','-o','ConnectTimeout=8','-o','UserKnownHostsFile='+CONFIG['ssh_known_hosts']]
 if CONFIG.get('ssh_identity_file'):args+=['-i',CONFIG['ssh_identity_file']]
 if CONFIG.get('ssh_user'):args+=['-l',CONFIG['ssh_user']]
 return args+[host]
def manifests():
 for root in MANIFEST_DIRS:
  if root.is_dir():
   for path in sorted(root.glob('job*.json')):yield path
