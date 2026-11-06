#!/usr/bin/env python3
"""Read-only Linux new-install preflight. Refuses service/data adoption and collisions."""
import argparse,json,os,pathlib,platform,socket,subprocess,sys
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',required=True,type=pathlib.Path);p.add_argument('--engine',default='docker');a=p.parse_args();c=json.loads(a.config.read_text());faults=[]
if platform.system()!='Linux' or platform.machine()!='x86_64':faults.append('Control-plane binaries require Linux x86_64; run Windows staging separately')
if not faults:
 import pwd,grp
 try:
  u=pwd.getpwnam(c['service_user']);g=grp.getgrnam(c['service_group'])
  if u.pw_uid!=int(c['service_uid']) or g.gr_gid!=int(c['service_gid']):faults.append('Existing service identity UID/GID mismatch')
 except KeyError:faults.append('Dedicated service identity not provisioned')
 def capture(args):return subprocess.run(args,check=True,capture_output=True,text=True).stdout
 try:
  capture([a.engine,'version']);capture([a.engine,'compose','version'])
  names=capture([a.engine,'ps','-a','--format','{{.Names}}']).splitlines()
  if any(x.startswith('iren-mkz-p2p-') or x.startswith('nvis-p2p-') for x in names):faults.append('Existing P2P containers found; preserve and review upgrade/adoption')
  volumes=capture([a.engine,'volume','ls','--format','{{.Name}}']).splitlines()
  if any(x in volumes for x in ['iren-mkz-p2p-postgres-data','iren-mkz-p2p-redis-data']):faults.append('Existing P2P volume found; do not overwrite/adopt silently')
  for name in ['manager','scheduler','seed']:
   unit='iren-mkz-p2p-'+name+'.service';state=capture(['systemctl','show',unit,'--property=LoadState','--value']).strip()
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
 if root.resolve()!=pathlib.Path(__file__).resolve().parents[1]:faults.append('install_root must equal this extracted kit directory')
 for path in [root,root/'state',root/'origin']:
  if '..' in path.parts or not path.is_absolute() or len(path.parts)<4 or any(q.is_symlink() for q in [path,*path.parents]):faults.append('Unsafe/broad/symlink deployment path: '+str(path))
  if path!=root and path.exists() and any(path.iterdir()):faults.append('New install refuses nonempty state/origin directory: '+str(path))
print(json.dumps({'result':'PASS' if not faults else 'STOP','read_only':True,'faults':faults},indent=2));sys.exit(78 if faults else 0)
