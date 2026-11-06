"""Isolated end-to-end fixtures; never contacts a scheduler or remote customer host."""
import os,sys,tempfile,json,hashlib,gzip,subprocess,shlex,tarfile,sqlite3
from pathlib import Path
base=Path(__file__).resolve().parents[1];sandbox=Path(tempfile.mkdtemp(prefix='portable-slurm-evidence-test-'));root=sandbox/'lake-root';root.mkdir();(root/'app').mkdir();(root/'app/README.md').write_text('isolated test export')
config=json.loads((base/'examples/cluster.example.json').read_text());config.update(root=str(root),cluster='fixture-cluster',site='fixture-site',epoch='fixture-epoch',controller_log=str(sandbox/'controller/slurmctld.log'),completion_log=str(sandbox/'controller/completions.log'),manifest_dirs=[str(root/'state/job-manifests')],local_roots=[str(sandbox/'validation')],remote_allowed_roots=[str(sandbox/'remote')],browser_auth_file=str(sandbox/'token'))
config_path=sandbox/'cluster.json';config_path.write_text(json.dumps(config));os.environ['SLURM_HISTORY_CONFIG']=str(config_path);sys.path.insert(0,str(base/'app'));(sandbox/'token').write_text('fixture-only-token-with-more-than-32-bytes');(sandbox/'controller').mkdir();(sandbox/'controller/slurmctld.log').write_text('JobId=1 JobId=3\n');(sandbox/'controller/completions.log').write_text('JobId=1 Name=fixture JobState=COMPLETED StartTime=2026-01-01T00:00:00 EndTime=2026-01-01T00:00:01\n');(sandbox/'validation').mkdir()
import history as h
checks=[]
def mark(name):checks.append(name)
c=h.db();raw=b'Step Time : 1.00s GPU utilization: 210.0MODEL_TFLOP/s/GPU Step Time : 2.00s GPU utilization: 220.0MODEL_TFLOP/s/GPU\niteration 1/50 | elapsed time per iteration (ms): 1000.0 | lm loss: 1\niteration 2/50 | elapsed time per iteration (ms): 2000.0 | lm loss: 2\n'
h.record(c,'/test/job1/log.out',raw,job=1);h.record(c,'/test/job1/log.out',raw,job=1);assert c.execute('select count(*) from artifacts').fetchone()[0]==1;mark('immutable_idempotence')
assert c.execute("select iteration,value from metrics where metric='modeled_throughput' order by iteration").fetchall()==[(1,210.0),(2,220.0)];mark('interleaved_metric_pairing')
append=raw+b'iteration 3/50 | elapsed time per iteration (ms): 900 | lm loss: 0.5\n';h.record(c,'/test/job1/log.out',append,job=1);assert c.execute('select count(*) from artifacts').fetchone()[0]==2;mark('append_versions')
h.record(c,'/test/job3/config.json',b'{"password":"fixture-secret","job_id":3}',job=3);assert c.execute('select redacted from artifacts where job_id=3').fetchone()[0]==1;mark('redaction')
c.commit();c.close();c=h.db();assert c.execute('select count(*) from artifacts').fetchone()[0]==3;mark('checkpoint_reopen')
h.record(c,'/alias/job1/log.out',append,job=1);c.commit();status=h.publish(c);assert status['missing_job_ids']==[2];assert status['slurm_cluster']=='fixture-cluster' and status['cluster_epoch']=='fixture-epoch';mark('configured_identity_and_explicit_gap')
import duckdb
q=duckdb.connect();gen=(root/'lake/current').resolve();assert q.execute("select count(*) from read_parquet(?) where job_id=1 and iteration=1 and metric='iteration_time'",[str(gen/'metrics.parquet')]).fetchone()[0]==1;mark('canonical_deduplication')
sha=hashlib.sha256(append).hexdigest();pieces=q.execute('select data from read_parquet(?) order by chunk',[str(root/'lake/payloads'/(sha+'.parquet'))]).fetchall();assert b''.join(r[0] for r in pieces)==append;mark('parquet_payload_roundtrip')
c.close();h.export();archive=next((root/'export').glob('*.tar.gz'));extract=sandbox/'export';extract.mkdir()
with tarfile.open(archive) as t:t.extractall(extract,filter='data')
r=subprocess.run([sys.executable,str(base/'tools/verify_export.py'),str(extract)],capture_output=True,text=True);assert r.returncode==0,r.stderr;mark('standalone_export_checksums')
from browser import app
client=app.test_client();headers={'X-Evidence-Token':(sandbox/'token').read_text()};assert client.get('/api/health').status_code==401;assert client.get('/api/health',headers={'X-Evidence-Token':'wrong'}).status_code==401;assert client.get('/api/health',headers=headers).status_code==200;mark('browser_auth_fail_closed')
assert client.get('/api/query',query_string={'sql':'select * from read_csv_auto(\'/etc/passwd\')'},headers=headers).status_code==400;assert client.get('/api/query',query_string={'sql':'select count(*) from jobs'},headers=headers).status_code==200;mark('read_only_sql_and_external_io_block')
# Generic scheduler discovery, including two concurrent jobs; no real scheduler access.
import metadata
slurm_output=('JobId=11 JobName=validation_a BatchFlag=1 NodeList=compute[001-002] BatchHost=compute001 JobState=RUNNING StdOut='+str(sandbox/'remote/11/master.out')+' StdErr='+str(sandbox/'remote/11/master.err')+'\nJobId=12 JobName=validation_b BatchFlag=0 NodeList=compute001 BatchHost=compute001 JobState=RUNNING\n').encode()
def fake_command(args,timeout=25):
 if args[-3:]==['show','jobs','-o']:return slurm_output
 if 'hostnames' in args:return b'compute001\ncompute002\n' if args[-1]=='compute[001-002]' else b'compute001\n'
 if 'batch_script' in args:Path(args[-1]).write_text('#!/bin/bash\necho fixture\n');return b''
 raise AssertionError(args)
metadata.command=fake_command;h.command=fake_command;metadata.main();assert len(list((root/'state/job-manifests').glob('job*.json')))==2;mark('multi_job_scheduler_discovery')
# Remote read fixture executes the bounded read helper locally. No SSH connection.
import live
remote=sandbox/'remote/11';remote.mkdir(parents=True);(remote/'master.out').write_text('iteration 1/50 | elapsed time per iteration (ms): 10 | lm loss: 1\n');(remote/'master.err').write_text('fixture stderr\n');(remote/'validation.json').write_text('{"job_id":11,"passed":true}');(remote/'credentials.json').write_text('fixture-secret-do-not-collect');(sandbox/'outside').write_text('not approved')
def local_remote_command(args,timeout=25):
 if args[0]!='ssh':return fake_command(args,timeout)
 p=subprocess.run(shlex.split(args[-1]),capture_output=True,timeout=timeout,check=True);return p.stdout
live.command=local_remote_command
job={'job_id':11,'nodes':['compute001','compute002'],'batch_host':'compute001','experiment':str(remote),'stdout':str(remote/'master.out'),'stderr':str(remote/'master.err')};live.capture_host(job,'compute001');c=h.db();assert c.execute("select count(*) from artifacts where job_id=11 and source like 'ssh://%master.err'").fetchone()[0]==1;assert c.execute("select count(*) from artifacts where source like '%credentials.json'").fetchone()[0]==0;assert c.execute("select status from remote_coverage where job_id=11 and host='compute001'").fetchone()[0]=='inventoried';c.close();mark('remote_stdout_stderr_validation_and_exclusions')
job['experiment']=str(sandbox/'outside');live.capture_host(job,'compute002');c=h.db();assert c.execute("select status from remote_coverage where job_id=11 and host='compute002'").fetchone()[0]=='partial';c.close();mark('remote_path_allowlist')
def fail_ssh(args,timeout=25):raise OSError('fixture unreachable')
live.command=fail_ssh;live.capture_host(job,'compute001');c=h.db();assert c.execute("select count(*) from errors where resolved_utc is null and source='remote/job11/compute001'").fetchone()[0]==1;c.close();mark('ssh_failure_is_explicit')
# Renderer is non-mutating and generates all 13 units.
render_config=json.loads((base/'examples/cluster.example.json').read_text());rc=sandbox/'render.json';rc.write_text(json.dumps(render_config));rendered=sandbox/'rendered';p=subprocess.run([sys.executable,str(base/'tools/render_deployment.py'),'--config',str(rc),'--output',str(rendered)],capture_output=True,text=True);assert p.returncode==0,p.stderr;assert len(list((rendered/'systemd').glob('*')))==13;assert all('RequiresMountsFor=' in p.read_text() for p in (rendered/'systemd').glob('*.service'));mark('rendered_mount_dependencies_and_units')
# Reopen the actual checkpoint in an independent process.
child="import history as h; c=h.db(); assert c.execute('select count(*) from artifacts').fetchone()[0]>=3; c.close(); print('checkpoint persisted')"
env=dict(os.environ,PYTHONPATH=str(base/'app'));r=subprocess.run([sys.executable,'-c',child],env=env,capture_output=True,text=True);assert r.returncode==0,r.stderr;mark('independent_process_checkpoint_recovery')
# Simulate a partial durable FTS cache entry without a completion marker, then rerun twice.
search=sqlite3.connect(root/'state/search.sqlite');search.execute('create virtual table chunks using fts5(sha UNINDEXED,part UNINDEXED,text)');search.execute('create table indexed(sha text primary key,bytes integer,utc text)');search.execute('insert into chunks values(?,?,?)',(sha,0,'partial fixture'));search.commit();search.close()
for attempt in range(2):
 r=subprocess.run([sys.executable,str(base/'app/search_index.py')],env=env,capture_output=True,text=True);assert r.returncode==0,r.stderr
search=sqlite3.connect(root/'state/search.sqlite');assert search.execute('select count(*) from indexed where sha=?',(sha,)).fetchone()[0]==1;assert search.execute('select count(*) from chunks where sha=?',(sha,)).fetchone()[0]==1;search.close();mark('partial_fulltext_recovery_and_idempotence')
# Accounting records retain raw job/step evidence, while identity remains explicitly scoped.
import accounting
accounting.CONFIG['accounting_enabled']=True
accounting.command=lambda args,timeout=25:json.dumps({'jobs':[{'job_id':21,'name':'fixture-accounting','steps':[{'step_id':'batch','state':'COMPLETED'}]}]}).encode()
accounting.collect();c=h.db();assert c.execute("select count(*) from artifacts where job_id=21 and source like '%accounting.json'").fetchone()[0]==1;c.close();accounting.CONFIG['accounting_enabled']=False;mark('optional_accounting_job_step_raw_capture')
# Validate concrete systemd units with actual executable paths, without installing them.
runtime=sandbox/'render-runtime';render_config['root']=str(runtime);render_config['manifest_dirs']=[str(runtime/'state/job-manifests')];rc=sandbox/'verify-render.json';rc.write_text(json.dumps(render_config));target=sandbox/'verify-render';r=subprocess.run([sys.executable,str(base/'tools/render_deployment.py'),'--config',str(rc),'--output',str(target)],capture_output=True,text=True);assert r.returncode==0,r.stderr
runtime.mkdir();(runtime/'app').mkdir();(runtime/'venv/bin').mkdir(parents=True);(runtime/'venv/bin/python').symlink_to(sys.executable)
r=subprocess.run(['systemd-analyze','verify',*[str(p) for p in (target/'systemd').glob('*')]],capture_output=True,text=True);assert r.returncode==0,r.stderr;mark('systemd_analyze_verify_all_13_units')
watchdog=next((target/'systemd').glob('*-watchdog.service')).read_text();assert 'ExecStart=/usr/bin/systemctl start ' in watchdog and '/app/watchdog.py' not in watchdog;mark('watchdog_has_no_root_execution_of_user_writable_source')
r=subprocess.run([sys.executable,str(base/'tools/backup_checkpoint.py'),'--config',str(config_path),'--output',str(sandbox/'checkpoint-backup.sqlite')],capture_output=True,text=True);assert r.returncode==0,r.stderr;backup=sqlite3.connect(sandbox/'checkpoint-backup.sqlite');assert backup.execute('select count(*) from artifacts').fetchone()[0]>0;backup.close();mark('online_sqlite_backup_and_integrity')
result={'status':'PASS','checks':checks,'check_count':len(checks),'fixture_root':str(sandbox),'real_scheduler_contacted':False,'real_customer_reboot_tested':False};print(json.dumps(result,indent=2))
