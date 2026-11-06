#!/usr/bin/env python3
"""Read-only Linux new-install preflight. Refuses service/data adoption and collisions."""
import argparse,json,os,pathlib,platform,socket,subprocess,sys
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',required=True,type=pathlib.Path);p.add_argument('--engine',default='docker');a=p.parse_args();c=json.loads(a.config.read_text());faults=[]
service_mode=c.get('service_mode','system')
if service_mode not in ['system','user']:faults.append('service_mode must be system or user')
if platform.system()!='Linux' or platform.machine()!='x86_64':faults.append('Control-plane binaries require Linux x86_64; run Windows staging separately')
if not faults:
 import pwd,grp
 try:
  u=pwd.getpwnam(c['service_user']);g=grp.getgrnam(c['service_group'])
  if u.pw_uid!=int(c['service_uid']) or g.gr_gid!=int(c['service_gid']):faults.append('Existing service identity UID/GID mismatch')
 except KeyError:faults.append('Dedicated service identity not provisioned')
 def capture(args):return subprocess.run(args,check=True,capture_output=True,text=True).stdout
 if service_mode=='user':
  if c.get('control_hostname')!=socket.gethostname():faults.append('User service control_hostname must match this exact host; shared home units require a host guard')
  if os.geteuid()!=int(c['service_uid']) or os.getegid()!=int(c['service_gid']):faults.append('User services must be rendered/installed by the configured service UID/GID')
  try:
   if capture(['loginctl','show-user',c['service_user'],'--property=Linger','--value']).strip()!='yes':faults.append('Persistent user services require approved lingering for the service account')
  except (OSError,subprocess.CalledProcessError) as e:faults.append('User lingering prerequisite check failed: '+str(e))
 try:
  capture([a.engine,'version']);capture([a.engine,'compose','version'])
  names=capture([a.engine,'ps','-a','--format','{{.Names}}']).splitlines()
  if any(x.startswith('example-site-p2p-') or x.startswith('nvis-p2p-') for x in names):faults.append('Existing P2P containers found; preserve and review upgrade/adoption')
  volumes=capture([a.engine,'volume','ls','--format','{{.Name}}']).splitlines()
  if any(x in volumes for x in ['example-site-p2p-postgres-data','example-site-p2p-redis-data']):faults.append('Existing P2P volume found; do not overwrite/adopt silently')
  for name in ['manager','scheduler','seed']:
   unit='example-site-p2p-'+name+'.service'
   scopes=[['--user']] if service_mode=='user' else [[]]
   for scope in scopes:
    state=capture(['systemctl',*scope,'show',unit,'--property=LoadState','--value']).strip()
    if state!='not-found':faults.append('Existing systemd unit: '+unit)
 except (OSError,subprocess.CalledProcessError) as e:faults.append('Runtime/systemd prerequisite check failed: '+str(e))
 for address in ['127.0.0.1',c['control_ip']]:
  try:
   with socket.socket() as s:s.bind((address,0))
  except OSError:faults.append('Configured interface address is not locally bindable: '+address)
 for port in [int(c.get('console_port',4301)),12001,12002,12003,12004,12005,12110,12111,12112,12114,12115,12116,12130,15379,15432]:
  try:
   with socket.socket() as s:s.bind(('0.0.0.0',port))
  except OSError:faults.append('TCP listener collision: '+str(port))
 try:
  with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:s.bind(('0.0.0.0',12113))
 except OSError:faults.append('UDP listener collision:12113')
 root=pathlib.Path(c['install_root'])
 data_root=pathlib.Path(c.get('data_root',c['install_root']))
 if root.resolve()!=pathlib.Path(__file__).resolve().parents[1]:faults.append('install_root must equal this extracted kit directory')
 paths=[root,data_root/'state',data_root/'origin']
 if data_root!=root:paths.append(data_root)
 for path in paths:
  if '..' in path.parts or not path.is_absolute() or len(path.parts)<4 or any(q.is_symlink() for q in [path,*path.parents]):faults.append('Unsafe/broad/symlink deployment path: '+str(path))
  if path!=root and path.exists() and any(path.iterdir()):faults.append('New install refuses nonempty state/origin directory: '+str(path))
print(json.dumps({'result':'PASS' if not faults else 'STOP','read_only':True,'faults':faults},indent=2));sys.exit(78 if faults else 0)
