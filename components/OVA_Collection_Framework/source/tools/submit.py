#!/usr/bin/env python3
"""Submit a scalar sbatch job with durable script/config/run evidence registration."""
import argparse,json,os,subprocess,sys,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--script',type=Path,required=True);p.add_argument('sbatch_args',nargs=argparse.REMAINDER);a=p.parse_args();cfg=json.loads(a.config.read_text());run=a.run_dir.resolve();script=a.script.resolve()
if not any(run.is_relative_to(Path(x).resolve()) for x in cfg['local_roots']+cfg['remote_allowed_roots']):raise SystemExit('Run directory must be within approved capture roots')
args=a.sbatch_args[1:] if a.sbatch_args[:1]==['--'] else a.sbatch_args
if any(x.startswith(('--array','--het-group','--wrap','--output','--error','--parsable')) or x.startswith(('-a','-o','-e')) for x in args):raise SystemExit('Wrapper supports scalar script jobs and manages output/error paths; array/heterogeneous jobs need an adapter')
if run.exists() and any(run.iterdir()):raise SystemExit('Use a new empty run directory for each submission')
run.mkdir(parents=True,exist_ok=True);submitted=run/'submitted.sbatch';submitted.write_bytes(script.read_bytes());os.chmod(submitted,0o600)
result=subprocess.run([str(Path(cfg['slurm_bin'])/'sbatch'),'--parsable','--output',str(run/'slurm-%j.out'),'--error',str(run/'slurm-%j.err'),*args,str(submitted)],capture_output=True,text=True)
if result.returncode:sys.stderr.write(result.stderr);raise SystemExit(result.returncode)
identity=result.stdout.strip().split(';')[0]
if not identity.isdecimal():raise SystemExit('Submission accepted but identity unsupported; inspect scheduler and register evidence manually')
job=int(identity);manifest=run/'collection-manifest.json';manifest.write_text(json.dumps({'job_id':job,'nodes':[],'experiment':str(run),'submitted_script_sha256':hashlib.sha256(submitted.read_bytes()).hexdigest(),'stdout':str(run/f'slurm-{job}.out'),'stderr':str(run/f'slurm-{job}.err'),'capture_contract':'shared durable run directory; discovered nodes merged by collector'},indent=2)+'\n')
r=subprocess.run([sys.executable,str(Path(__file__).with_name('write_job_manifest.py')),'--config',str(a.config),'--input',str(manifest)],capture_output=True,text=True)
if r.returncode:
    sys.stderr.write('Job '+str(job)+' was submitted; manifest registration failed. Preserve '+str(manifest)+' and register it before source retention expires.\n');raise SystemExit(2)
print(job)
