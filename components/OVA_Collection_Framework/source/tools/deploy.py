#!/usr/bin/env python3
"""Plan or install a fresh local deployment. Never contacts or reboots compute nodes."""
import argparse, fcntl, hashlib, json, os, pwd, grp, secrets, shutil, subprocess, sys, tempfile
from pathlib import Path
from configuration import load

BASE=Path(__file__).resolve().parents[1]
def run(args,**kwargs):return subprocess.run([str(x) for x in args],check=True,**kwargs)
def assert_no_symlinks(path):
    for p in [path,*path.parents]:
        if p.is_symlink():raise ValueError('Deployment paths must not traverse symlinks: '+str(p))
def jobcomp_plan(config,path):
    import re
    text=Path(path).read_text()
    if re.search(r'^\s*Include\b',text,re.M|re.I):
        raise ValueError('Included Slurm configuration requires site review; existing integrations preserved')
    types=re.findall(r'^\s*JobCompType\s*=\s*(\S+)',text,re.M|re.I)
    locations=re.findall(r'^\s*JobCompLoc\s*=\s*(\S+)',text,re.M|re.I)
    if types and types[-1] not in ('jobcomp/none','none','jobcomp/filetxt'):
        raise ValueError('Existing completion plugin preserved; use its adapter or accounting instead')
    if types and types[-1]=='jobcomp/filetxt':
        if locations and locations[-1]==config['completion_log']:return text,text
        raise ValueError('Existing filetxt location differs; configure the collector to match it')
    if re.search(r'^\s*(Include|JobCompLoc)\b',text,re.M|re.I):
        raise ValueError('Included/existing Slurm configuration needs site review; use an existing durable source')
    new=re.sub(r'^\s*JobCompType\s*=.*$','',text,flags=re.M|re.I)
    return text,new+'\n# OVA Collection Framework: native durable completion feed\nJobCompType=jobcomp/filetxt\nJobCompLoc='+config['completion_log']+'\n'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['plan','apply']);p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--wheelhouse',type=Path);p.add_argument('--configure-jobcomp',type=Path,metavar='SLURM_CONF');p.add_argument('--slurm-user',default='slurm');a=p.parse_args()
    c=load(a.config);root=Path(c['root']);out=a.output.resolve();assert_no_symlinks(root)
    change=jobcomp_plan(c,a.configure_jobcomp) if a.configure_jobcomp else None
    run([sys.executable,BASE/'tools/render_deployment.py','--config',a.config.resolve(),'--output',out])
    plan=json.loads((out/'deployment-plan.json').read_text())
    plan.update(native_completion_plugin='jobcomp/filetxt',scheduler_configuration_change_requested=bool(change),scheduler_reboot=False,node_changes=False,source_checks=['controller_log','completion_log','local_roots'],browser_url='http://127.0.0.1:'+str(c['browser_port'])+'/login')
    (out/'deployment-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    if a.mode=='plan':print(json.dumps(plan,indent=2));return
    if os.geteuid()!=0:raise SystemExit('apply requires root on the designated collector host')
    if (root/'app').exists() or (root/'state/index.sqlite').exists():raise SystemExit('Existing deployment preserved. Use documented maintenance/rollback; fresh installer refuses to overwrite it.')
    for exe in ['systemctl','systemd-analyze','useradd','groupadd','runuser',str(Path(c['slurm_bin'])/'scontrol')]:
        if not shutil.which(exe):raise SystemExit('Missing deployment prerequisite: '+exe)
    # Persistent mount has to be commissioned before the installer; tmpfs cannot hold the lake.
    fs=subprocess.check_output(['findmnt','-n','-o','FSTYPE','-T',str(root.parent if root.parent.exists() else '/var/lib')],text=True).strip()
    if fs in ('tmpfs','ramfs','overlay'):raise SystemExit('Persistent host storage required; temporary/container filesystem rejected')
    if not change and not Path(c['completion_log']).is_file() and not c['accounting_enabled']:
        raise SystemExit('A durable completion feed or verified accounting is required before job 1. Configure an existing feed or use --configure-jobcomp /path/to/slurm.conf.')
    lock_path=Path('/run/lock/ova-collection-'+c['cluster']+'-'+c['epoch']+'.lock')
    with lock_path.open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:grp.getgrnam(c['service_group'])
        except KeyError:run(['groupadd','--system',c['service_group']])
        try:account=pwd.getpwnam(c['service_user'])
        except KeyError:
            run(['useradd','--system','--gid',c['service_group'],'--home-dir',root,'--no-create-home','--shell','/usr/sbin/nologin',c['service_user']]);account=pwd.getpwnam(c['service_user'])
        group=grp.getgrnam(c['service_group']);root.mkdir(parents=True,exist_ok=True);os.chmod(root,0o750);os.chown(root,account.pw_uid,group.gr_gid)
        for name in ['state','raw','lake','export']:
            d=root/name;d.mkdir(exist_ok=True);os.chmod(d,0o700);os.chown(d,account.pw_uid,group.gr_gid)
        for d in c['manifest_dirs']:
            Path(d).mkdir(parents=True,exist_ok=True);os.chmod(d,0o750);os.chown(d,account.pw_uid,group.gr_gid)
        shutil.copytree(out/'app',root/'app');shutil.copytree(BASE/'tools',root/'tools',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copy2(a.config,root/'cluster.json');os.chmod(root/'cluster.json',0o640);os.chown(root/'cluster.json',0,group.gr_gid)
        run([sys.executable,'-m','venv',root/'venv'])
        args=[root/'venv/bin/python','-m','pip','install']
        if a.wheelhouse:args+=['--no-index','--find-links',a.wheelhouse.resolve()]
        run(args+['-r',root/'app/requirements.lock'])
        token=Path(c['browser_auth_file']);assert_no_symlinks(token)
        if not token.exists():
            token.parent.mkdir(parents=True,exist_ok=True)
            fd=os.open(token,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o640)
            with os.fdopen(fd,'w') as f:f.write(secrets.token_urlsafe(48)+'\n');f.flush();os.fsync(f.fileno())
        os.chmod(token,0o640);os.chown(token,0,group.gr_gid)
        if len(token.read_text().strip())<32:raise SystemExit('Browser token must contain at least 32 characters')
        if change and change[0]!=change[1]:
            conf=a.configure_jobcomp.resolve();assert_no_symlinks(a.configure_jobcomp)
            slurm=pwd.getpwnam(a.slurm_user);completion=Path(c['completion_log']);assert_no_symlinks(completion)
            if completion.exists():raise SystemExit('Refuse to repurpose an existing terminal evidence file')
            parent_existed=completion.parent.exists();completion.parent.mkdir(parents=True,exist_ok=True)
            if not parent_existed:os.chmod(completion.parent,0o750);os.chown(completion.parent,slurm.pw_uid,group.gr_gid)
            completion.touch(mode=0o640);os.chown(completion,slurm.pw_uid,group.gr_gid)
            backup=conf.with_name(conf.name+'.ova-backup-'+hashlib.sha256(change[0].encode()).hexdigest()[:12])
            if not backup.exists():shutil.copy2(conf,backup)
            temporary=conf.with_name(conf.name+'.ova-new');temporary.write_text(change[1]);shutil.copystat(conf,temporary);st=conf.stat();os.chown(temporary,st.st_uid,st.st_gid);os.replace(temporary,conf)
            try:run([Path(c['slurm_bin'])/'scontrol','reconfigure'])
            except subprocess.CalledProcessError:
                shutil.copy2(backup,conf);raise SystemExit('Slurm reconfiguration failed; configuration restored. Verify the running scheduler before retrying.')
        run(['systemd-analyze','verify',*sorted((out/'systemd').glob('*'))])
        environment=dict(os.environ,SLURM_HISTORY_CONFIG=str(root/'cluster.json'))
        # These are the installed permissions, not root's view of source readability.
        run(['runuser','-u',c['service_user'],'-g',c['service_group'],'--',root/'venv/bin/python',root/'tools/preflight.py','--config',root/'cluster.json'],env=environment)
        for script in ['metadata.py','history.py']:
            run(['runuser','-u',c['service_user'],'-g',c['service_group'],'--',root/'venv/bin/python',root/'app'/script],env=environment)
        for unit in (out/'systemd').glob('*'):shutil.copy2(unit,Path('/etc/systemd/system')/unit.name)
        run(['systemctl','daemon-reload']);run(['systemctl','enable','--now',*plan['enable_units']])
        receipt={'status':'INSTALLED_REQUIRES_COMMISSIONING','cluster':c['cluster'],'epoch':c['epoch'],'configuration_sha256':hashlib.sha256(a.config.read_bytes()).hexdigest(),'root':str(root),'enable_units':plan['enable_units'],'real_reboot_tested':False,'first_job_capture_verified':False,'hub_upload_performed':False}
        (root/'deployment-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');os.chmod(root/'deployment-receipt.json',0o640)
        print(json.dumps({'receipt':str(root/'deployment-receipt.json'),'browser_url':plan['browser_url'],'browser_token_file':str(token),'next':'Run docs/acceptance.md before opening validation submissions.'},indent=2))
if __name__=='__main__':main()
