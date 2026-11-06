#!/usr/bin/env python3
"""Render a reviewed deployment; performs no privileged installation or Slurm mutation."""
import argparse,json,re,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();c=json.loads(a.config.read_text());out=a.output
if out.exists() and any(out.iterdir()):raise SystemExit('Output must be empty; preserve prior rendered releases')
for key in ['root','slurm_bin','controller_log','completion_log','ssh_known_hosts','ssh_identity_file','browser_auth_file']:
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+',c[key]):raise SystemExit('Use an absolute path without whitespace/metacharacters: '+key)
for key in ['service_user','service_group','cluster','epoch']:
    if not re.fullmatch(r'[A-Za-z0-9_-]+',c[key]):raise SystemExit('Invalid identifier: '+key)
for key in ['manifest_dirs','local_roots','remote_allowed_roots']:
    if not isinstance(c[key],list) or any(not re.fullmatch(r'/[A-Za-z0-9_./-]+',x) for x in c[key]):raise SystemExit('Invalid paths in '+key)
if not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service',c['slurm_service']):raise SystemExit('Invalid Slurm service unit')
if not 1024<=int(c['browser_port'])<=65535:raise SystemExit('Invalid unprivileged browser port')
root=c['root'];prefix='slurm-evidence-'+c['cluster']+'-'+c['epoch'];unitdir=out/'systemd';unitdir.mkdir(parents=True);source=Path(__file__).resolve().parents[1]/'app';shutil.copytree(source,out/'app',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));(out/'cluster.json').write_text(json.dumps(c,indent=2)+'\n')
common=f'''User={c['service_user']}
Group={c['service_group']}
WorkingDirectory={root}/app
Environment=SLURM_HISTORY_CONFIG={root}/cluster.json
UMask=0077
Nice=15
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths={root}
'''
tasks={'metadata':('metadata.py',60,'25%','384M',5,15),'live':('live.py',180,'25%','768M',10,15),'scan':('history.py',600,'50%','1500M',15,60),'remote-backfill':('backfill_remote.py',180,'25%','768M',120,120),'search':('search_index.py',120,'50%','512M',30,5)}
for name,(script,timeout,cpu,mem,boot,interval) in tasks.items():
    svc=f'{prefix}-{name}.service'
    text=f'''[Unit]
Description=Slurm evidence {name} for {c['cluster']} {c['epoch']}
After=network-online.target {c['slurm_service']}
Wants=network-online.target
RequiresMountsFor={root}
[Service]
Type=oneshot
{common}ExecStart={root}/venv/bin/python {root}/app/{script}
TimeoutStartSec={timeout}
CPUQuota={cpu}
MemoryMax={mem}
IOWeight=10
IOSchedulingClass=idle
Restart=on-failure
RestartSec=15s
''';(unitdir/svc).write_text(text)
    (unitdir/f'{prefix}-{name}.timer').write_text(f'''[Unit]
Description=Repeated Slurm evidence {name}
[Timer]
OnBootSec={boot}s
OnUnitInactiveSec={interval}s
AccuracySec=1s
Unit={svc}
[Install]
WantedBy=timers.target
''')
(unitdir/f'{prefix}-browser.service').write_text(f'''[Unit]
Description=Loopback authenticated Slurm evidence browser
After=network-online.target
RequiresMountsFor={root}
[Service]
Type=simple
{common}ExecStart={root}/venv/bin/python {root}/app/browser.py
Restart=always
RestartSec=5s
CPUQuota=100%
MemoryMax=768M
[Install]
WantedBy=multi-user.target
''')
watched=[f'{prefix}-browser.service']+[f'{prefix}-{n}.timer' for n in tasks]
(unitdir/f'{prefix}-watchdog.service').write_text(f'''[Unit]
Description=Restart stopped evidence services and timers
After=network-online.target
RequiresMountsFor={root}
[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl start {' '.join(watched)}
TimeoutStartSec=120
CPUQuota=10%
MemoryMax=128M
UMask=0077
''')
(unitdir/f'{prefix}-watchdog.timer').write_text(f'''[Unit]
Description=Evidence service availability watchdog
[Timer]
OnBootSec=30s
OnUnitInactiveSec=60s
[Install]
WantedBy=timers.target
''')
(out/'deployment-plan.json').write_text(json.dumps({'root':root,'prefix':prefix,'enable_units':[f'{prefix}-browser.service']+[f'{prefix}-{n}.timer' for n in [*tasks,'watchdog']],'reference':'Read the handoff; renderer does not alter Slurm or install credentials.'},indent=2)+'\n')
print(out)
