#!/usr/bin/env python3
"""Render the offline minimal Dragonfly control plane; default checks inputs without writing."""
from __future__ import annotations
import argparse,hashlib,ipaddress,json,os,pathlib,re,shutil,stat,sys
KIT=pathlib.Path(__file__).resolve().parents[1]
def secret(path):
 p=pathlib.Path(path)
 if not p.is_absolute() or not p.is_file() or p.is_symlink():raise ValueError('Secret/certificate must be an existing absolute regular file')
 if stat.S_IMODE(p.stat().st_mode)&0o077:raise ValueError('Secret must have mode0600 or stricter: '+str(p))
 value=p.read_text().rstrip('\r\n')
 if not value or '\n' in value or '\r' in value:raise ValueError('Password/JWT must contain one nonempty line')
 return value

def directory(value):
 p=pathlib.Path(value)
 if not p.is_absolute() or '..' in p.parts or len(p.parts)<4 or not re.fullmatch(r'/[A-Za-z0-9_./-]+',value):raise ValueError('Use a dedicated absolute Linux directory without .. or whitespace')
 for q in [p,*p.parents]:
  if q.is_symlink():raise ValueError('Symlink ancestry refused: '+str(q))
 return p

def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def dump(out,relative,data,mode=0o644):
 p=out/relative;p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(data,indent=2)+'\n' if isinstance(data,(dict,list)) else data);p.chmod(mode)

def bind_client_interfaces(config, address):
 """Bind client listeners using the pinned 1.4.9 server schema."""
 for section in ['upload','proxy','metrics','health','stats']:
  if section in config:
   config[section].pop('ip',None)
   config[section].setdefault('server',{})['ip']=address
 config['storage'].setdefault('server',{})['ip']=address
 # Source fallback is a request/CLI control in 1.4.9, not a Scheduler field.
 config['scheduler'].pop('enableBackToSource',None)
 return config

def native_unit(description, command, cfg, *, working_directory=None, after=None, host=None):
 """Render either a system service or the same user's persistent service."""
 user_service=cfg.get('service_mode','system')=='user'
 target_host=host or cfg.get('control_hostname')
 if user_service and not target_host:raise ValueError('User services require an exact control_hostname host guard')
 if target_host and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,252}',target_host):raise ValueError('Use an exact hostname for the service host guard')
 guard=f'ConditionHost={target_host}\n' if target_host else ''
 identity='' if user_service else f'User={cfg["service_user"]}\nGroup={cfg["service_group"]}\n'
 target='default.target' if user_service else 'multi-user.target'
 ordering=(f'After={after}\n' if after else '') if user_service else 'After=network-online.target'+(' '+after if after else '')+'\nWants=network-online.target\n'
 limits='' if user_service else 'LimitNOFILE=1048576\n'
 working=f'WorkingDirectory={working_directory}\n' if working_directory else ''
 return f'[Unit]\nDescription={description}\n{guard}{ordering}\n[Service]\nType=simple\n{identity}{working}ExecStart={command}\nRestart=always\nRestartSec=5s\n{limits}NoNewPrivileges=true\n\n[Install]\nWantedBy={target}\n'

def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--config',required=True,type=pathlib.Path);a.add_argument('--output',type=pathlib.Path);a.add_argument('--peer-config',type=pathlib.Path);args=a.parse_args()
 cfg=json.loads(args.config.read_text());root=directory(cfg['install_root']);data_root=directory(cfg.get('data_root',cfg['install_root']));ip=ipaddress.ip_address(cfg['control_ip'])
 if cfg.get('service_mode','system') not in ['system','user']:raise ValueError('service_mode must be system or user')
 if cfg.get('service_mode','system')=='user' and not cfg.get('control_hostname'):raise ValueError('User services require control_hostname so shared home units cannot run on other hosts')
 if ip.version!=4 or ip.is_loopback or ip.is_unspecified or ip.is_multicast or any(ip in ipaddress.ip_network(n) for n in ['192.0.2.0/24','198.51.100.0/24','203.0.113.0/24','192.0.2.0/24']):raise ValueError('Use the real local example compute-facing IPv4 address, not a template or loopback')
 cidr=ipaddress.ip_network(cfg['origin_allow_cidr'],strict=True)
 if cidr.version!=4 or cidr.prefixlen==0 or cidr.is_multicast or cidr.is_reserved or cidr.network_address.is_unspecified or any(cidr.overlaps(ipaddress.ip_network(n)) for n in ['192.0.2.0/24','198.51.100.0/24','203.0.113.0/24','192.0.2.0/24']):raise ValueError('Use the approved bounded example compute CIDR')
 port=int(cfg.get('console_port',4301))
 if not 1024<=port<=65535:raise ValueError('console_port must be1024..65535')
 for field in ['service_user','service_group','site_id']:
  if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_.-]*',cfg[field]):raise ValueError('Invalid '+field)
 uid=int(cfg['service_uid']);gid=int(cfg['service_gid'])
 if not 0<uid<2**31 or not 0<gid<2**31:raise ValueError('Use an existing dedicated non-root service identity')
 postgres_password=secret(cfg['postgres_password_file']);jwt=secret(cfg['manager_jwt_key_file'])
 key=pathlib.Path(cfg['tls_key_file']);cert=pathlib.Path(cfg['tls_cert_file'])
 if not key.is_absolute() or not cert.is_absolute() or not key.is_file() or key.is_symlink() or stat.S_IMODE(key.stat().st_mode)&0o077 or not cert.is_file() or cert.is_symlink():raise ValueError('Existing TLS cert/key required; key mode0600 or stricter; localhost SAN required')
 rows=json.loads((KIT/'offline/image-inventory.json').read_text())
 for x in rows:
  if digest(KIT/'offline'/x['archive'])!=x['archive_sha256']:raise ValueError('Offline image archive hash mismatch: '+x['name'])
 if args.peer_config:
  peer=json.loads(args.peer_config.read_text());node_ip=ipaddress.ip_address(peer['node_ip']);peerroot=directory(peer['peer_root'])
  if node_ip.version!=4 or node_ip.is_loopback or node_ip.is_unspecified or node_ip.is_multicast or node_ip not in cidr or any(node_ip in ipaddress.ip_network(n) for n in ['192.0.2.0/24','198.51.100.0/24','203.0.113.0/24','192.0.2.0/24']):raise ValueError('Real unicast compute-node IPv4 inside approved origin CIDR required')
  for field in ['hostname','rack']:
   if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',peer[field]):raise ValueError('Invalid peer '+field)
  if peer['architecture'] not in ['x86_64','aarch64-64k']:raise ValueError('Supported binaries: x86_64 or aarch64-64k only')
  if peer['architecture']=='aarch64-64k' and int(peer['page_size'])!=65536:raise ValueError('ARM peer requires65536-byte page compatibility')
 if not args.output:
  print(json.dumps({'status':'INPUT_CHECKS_PASS','mode':'read-only','images':len(rows),'console':'https://localhost:'+str(port),'MinIO_required':False,'writes':False}));return 0
 out=args.output
 if out.exists() or out.is_symlink():raise ValueError('Render output already exists; preserve it and choose a new reviewed path')
 out=directory(str(out));out.mkdir(parents=True,mode=0o700)
 # Runtime .yaml files contain JSON, a YAML1.2 subset; no PyYAML dependency on the offline target.
 def template(name):return json.loads((KIT/'templates'/(name+'.json')).read_text())
 if args.peer_config:
  d=template('peer.template');d['host']={'idc':cfg['site_id'],'location':peer['rack'],'hostname':peer['hostname'],'ip':str(node_ip)};d['server']={'pluginDir':str(peerroot/'plugins'),'cacheDir':str(peerroot/'cache')};d['download']['server']['socketPath']=str(peerroot/'run/dfdaemon.sock');d['manager']['addr']='http://'+str(ip)+':12003';d['storage']['dir']=str(peerroot/'storage');d['proxy']['disableBackToSource']=True
  d['health']={'server':{'port':12205}};d['stats']={'server':{'port':12206}}
  bind_client_interfaces(d,str(node_ip))
  dump(out,'peer.yaml',d);binary='client-amd64-v1.4.9' if peer['architecture']=='x86_64' else 'client-arm64-64k-v1.4.9'
  unit=native_unit('example site Dragonfly compute peer',f'{peerroot}/bin/dfdaemon --config {peerroot}/peer.yaml --log-dir {peerroot}/logs --console',cfg,host=peer.get('system_hostname',peer['hostname']))
  dump(out,'example-site-p2p-peer.service',unit)
  dump(out,'peer-install-plan.json',{'hostname':peer['hostname'],'ip':str(node_ip),'peer_root':str(peerroot),'source_binary_directory':str(root/'source/dist'/binary),'service_user':cfg['service_user'],'service_group':cfg['service_group'],'proxy_back_to_source':False,'dfget_required_arguments':['--disable-back-to-source'],'origin_metadata_required':True,'tcp_ports':[12200,12201,12202,12204,12205,12206],'udp_ports':[12203],'requires':'copy only these verified binaries/config to the exact approved node, preserve existing storage, install unit under reviewed scope'})
  print('Peer configuration rendered; no node contacted.');return 0
 manager=template('manager.example');manager['server']['logDir']=str(data_root/'state/manager/logs');manager['server']['pluginDir']=str(data_root/'state/manager/plugins');manager['server']['grpc']['advertiseIP']=str(ip);manager['server']['grpc']['listenIP']=str(ip);manager['server']['rest']['addr']='127.0.0.1:12004';manager['auth']['jwt']['key']=jwt;manager['database']['postgres']['password']=postgres_password;manager['metrics']['addr']=str(ip)+':12005';dump(out,'manager.yaml',manager,0o600)
 scheduler=template('scheduler');scheduler['server'].update({'advertiseIP':str(ip),'listenIP':str(ip),'logDir':str(data_root/'state/scheduler/logs'),'pluginDir':str(data_root/'state/scheduler/plugins'),'dataDir':str(data_root/'state/scheduler/data')});scheduler['manager']['addr']=str(ip)+':12003';scheduler['host']={'idc':cfg['site_id'],'location':'example-management'};scheduler['metrics']['addr']=str(ip)+':12001';dump(out,'scheduler.yaml',scheduler)
 seed=template('seed');seed['host']={'idc':cfg['site_id'],'location':'seed','hostname':'example-site-seed','ip':str(ip)};seed['server']={'pluginDir':str(data_root/'state/seed/plugins'),'cacheDir':str(data_root/'state/seed/cache')};seed['download']['server']['socketPath']=str(data_root/'state/seed/dfdaemon.sock');seed['manager']['addr']='http://'+str(ip)+':12003';seed['storage']['dir']=str(data_root/'state/seed/storage');seed['health']={'server':{'ip':str(ip),'port':12115}};seed['stats']={'server':{'ip':str(ip),'port':12116}};bind_client_interfaces(seed,str(ip));dump(out,'seed.yaml',seed)
 dump(out,'postgres-password',postgres_password+'\n',0o600)
 dump(out,'tls/server.crt',cert.read_text(),0o644);dump(out,'tls/server.key',key.read_text(),0o600)
 tags={x['name']:x['local_tag'] for x in rows}
 compose={'name':'example-site-p2p-minimal','services':{'postgres':{'image':tags['postgres'],'container_name':'example-site-p2p-postgres','environment':{'POSTGRES_USER':'nvis_p2p','POSTGRES_DB':'nvis_p2p','POSTGRES_PASSWORD_FILE':'/run/secrets/postgres_password'},'volumes':[str(out/'postgres-password')+':/run/secrets/postgres_password:ro','example-site-p2p-postgres-data:/var/lib/postgresql/data'],'ports':['127.0.0.1:15432:5432'],'restart':'unless-stopped','healthcheck':{'test':['CMD-SHELL','pg_isready -U nvis_p2p -d nvis_p2p'],'interval':'3s','timeout':'3s','retries':30}},'redis':{'image':tags['redis'],'container_name':'example-site-p2p-redis','command':['redis-server','--appendonly','yes'],'volumes':['example-site-p2p-redis-data:/data'],'ports':['127.0.0.1:15379:6379'],'restart':'unless-stopped','healthcheck':{'test':['CMD','redis-cli','ping'],'interval':'3s','timeout':'3s','retries':30}},'console':{'image':tags['nginx'],'container_name':'example-site-p2p-console','network_mode':'host','user':f'{uid}:{gid}','entrypoint':['nginx'],'command':['-g','daemon off;','-c','/etc/nginx/nginx.conf'],'read_only':True,'tmpfs':['/tmp:size=32m,mode=1777'],'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'volumes':[str(out/'nginx.conf')+':/etc/nginx/nginx.conf:ro',str(root/'console-static')+':/usr/share/nginx/html:ro',str(data_root/'origin')+':/srv/origin:ro',str(out/'tls/server.crt')+':/etc/nginx/tls/server.crt:ro',str(out/'tls/server.key')+':/etc/nginx/tls/server.key:ro'],'restart':'unless-stopped'}},'volumes':{'example-site-p2p-postgres-data':{'external':True},'example-site-p2p-redis-data':{'external':True}}};dump(out,'compose.yaml',compose)
 nginx=(KIT/'source/upstream/console/deploy/nginx.nvis.conf').read_text();nginx=re.sub(r'    listen [^;]+;\n','',nginx);nginx=nginx.replace('    server_name _;',f'    listen 127.0.0.1:{port} ssl;\n    ssl_certificate /etc/nginx/tls/server.crt;\n    ssl_certificate_key /etc/nginx/tls/server.key;\n    ssl_protocols TLSv1.2 TLSv1.3;\n    server_name localhost;');nginx=re.sub(r'    location /nvis/api/ \{.*?\n    \}','    location /nvis/api/ { return 403; }',nginx,flags=re.S);nginx=nginx.rsplit('}',1)[0]+f'  server {{ listen {ip}:12130; server_name _; root /srv/origin; autoindex off; allow {ip}; allow {cidr}; deny all; location / {{ try_files $uri =404; }} }}\n}}\n';dump(out,'nginx.conf',nginx)
 for name,binary,config in [('manager','core/manager','manager.yaml'),('scheduler','core/scheduler','scheduler.yaml'),('seed','client-amd64-v1.4.9/dfdaemon','seed.yaml')]:
  args=f'{root}/source/dist/{binary} --config {out}/{config}'
  if name=='seed':args+=f' --log-dir {data_root}/state/seed/logs'
  args+=' --console'
  after='example-site-p2p-manager.service' if name!='manager' else (None if cfg.get('service_mode','system')=='user' else 'docker.service')
  unit=native_unit('example site Dragonfly '+name,args,cfg,working_directory=root,after=after);dump(out,'systemd/example-site-p2p-'+name+'.service',unit)
 dump(out,'site-plan.json',{'root':str(root),'data_root':str(data_root),'site':str(out),'control_ip':str(ip),'console_port':port,'uid':uid,'gid':gid,'service_user':cfg['service_user'],'service_group':cfg['service_group'],'service_mode':cfg.get('service_mode','system'),'control_hostname':cfg.get('control_hostname'),'user_linger_required':cfg.get('service_mode','system')=='user','default_auth':'root/dragonfly (rotate at first login)','MinIO_required':False,'starts_nothing':True})
 if os.geteuid()==0:
  for p in [out,*out.rglob('*')]:os.chown(p,uid,gid)
 print('Rendered minimal site; no service started, no node contacted. Keep this output private.')
 return 0
if __name__=='__main__':
 try:sys.exit(main())
 except (OSError,ValueError,KeyError) as e:print('RENDER_STOPPED: '+str(e),file=sys.stderr);sys.exit(64)
