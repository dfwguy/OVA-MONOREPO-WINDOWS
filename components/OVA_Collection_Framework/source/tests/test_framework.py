"""Failure-boundary behavior for portable deployment, auth, replay and source bounds."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'tools'))
from configuration import load
from deploy import jobcomp_plan

class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.directory=Path(self.temp.name)
        self.config=json.loads((BASE/'examples/cluster.example.json').read_text());self.config.update(site='fixture-site',cluster='fixture-cluster',epoch='initial',root='/var/lib/slurm-evidence/fixture-cluster/initial',manifest_dirs=['/var/lib/slurm-evidence/fixture-cluster/initial/state/job-manifests'])
        self.path=self.directory/'private.json'
    def write(self):self.path.write_text(json.dumps(self.config));return self.path
    def test_unsafe_paths_and_root_identity_rejected(self):
        for key,value in [('root','/'),('root','/var/lib/slurm-evidence/../other'),('service_user','root'),('local_roots',['/']),('max_remote_batch_bytes',10**12),('manifest_dirs',['/etc/private'])]:
            with self.subTest(key=key,value=value):
                previous=self.config[key];self.config[key]=value
                with self.assertRaises(ValueError):load(self.write())
                self.config[key]=previous
    def test_plan_is_nonprivileged_and_fails_on_reused_output(self):
        self.write();out=self.directory/'render';args=[sys.executable,str(BASE/'tools/deploy.py'),'plan','--config',str(self.path),'--output',str(out)]
        result=subprocess.run(args,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(list((out/'systemd').glob('*'))),13);self.assertFalse(Path(self.config['root']).exists())
        self.assertNotEqual(subprocess.run(args,capture_output=True).returncode,0)
    def test_jobcomp_preserves_existing_plugins_and_includes(self):
        for text in ['JobCompType=jobcomp/kafka\n','Include /etc/slurm/site.conf\n','include /etc/slurm/site.conf\n','JobCompType=jobcomp/filetxt\nJobCompLoc=/another/path\n']:
            self.path.write_text(text)
            with self.assertRaises(ValueError):jobcomp_plan(self.config,self.path)
    def test_native_jobcomp_change_retains_unrelated_config(self):
        self.path.write_text('ClusterName=fixture-cluster\nJobCompType=jobcomp/none\n')
        before,after=jobcomp_plan(self.config,self.path)
        self.assertIn('ClusterName=fixture-cluster',after);self.assertIn('JobCompType=jobcomp/filetxt',after);self.assertNotIn('JobCompType=jobcomp/none',after);self.assertEqual(self.path.read_text(),before)
    def test_example_cannot_deploy_as_real_identity(self):
        self.path.write_text((BASE/'examples/cluster.example.json').read_text())
        with self.assertRaises(ValueError):load(self.path)

class CollectorBoundaryTests(unittest.TestCase):
    def test_auth_cursor_local_path_escape_and_fair_host_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);root=d/'root';root.mkdir();approved=d/'approved';approved.mkdir();outside=d/'outside';outside.write_text('outside-data-must-not-be-captured');(approved/'escape.log').symlink_to(outside);token=d/'token';token.write_text('fixture-only-credential-longer-than-thirty-two')
            config=json.loads((BASE/'examples/cluster.example.json').read_text());config.update(root=str(root),site='fixture',cluster='fixture',epoch='fixture',manifest_dirs=[str(root/'state/job-manifests')],local_roots=[str(approved)],controller_log=str(d/'controller.log'),completion_log=str(d/'completion.log'),browser_auth_file=str(token),remote_capture_enabled=True,accounting_enabled=True,accounting_poll_seconds=60,max_remote_hosts_per_pass=2)
            path=d/'config.json';path.write_text(json.dumps(config));env=dict(os.environ,SLURM_HISTORY_CONFIG=str(path),PYTHONPATH=str(BASE/'app'))
            code=r'''
import json,datetime as dt
from pathlib import Path
import history as h,accounting,live
from browser import app
c=h.db();h.local_scan(c);c.commit()
assert c.execute("select count(*) from artifacts where source like '%escape.log'").fetchone()[0]==0
assert c.execute("select count(*) from errors where message='outside approved local roots' and source like '%escape.log'").fetchone()[0]==1
c.close()
# Stream a stable file with several Parquet chunks, preserving exact original/stored hashes.
import hashlib,gzip,streaming,duckdb
large=Path(__import__('settings').CONFIG['local_roots'][0])/'job5-large.log'
body=(b'fixture raw log record\n'*100000)+b'password=fixture-sensitive\n'
large.write_bytes(body);c=h.db();version=streaming.capture(c,large,job=5)
row=c.execute('select sha256,stored_sha256,redacted from artifacts where version=?',(version,)).fetchone();assert row[0]==hashlib.sha256(body).hexdigest() and row[2]==1
raw=h.ROOT/'raw'/row[1][:2]/(row[1]+'.gz');clean=gzip.decompress(raw.read_bytes());assert b'fixture-sensitive' not in clean
payload=h.ROOT/'lake/large-fixture.parquet';streaming.publish_payload(raw,payload,row[1]);q=duckdb.connect();pieces=q.execute('select data from read_parquet(?) order by chunk',[str(payload)]).fetchall();assert b''.join(x[0] for x in pieces)==clean;q.close()
# A source changing while read is rejected, and staging files do not become committed artifacts.
from unittest.mock import patch
from types import SimpleNamespace
original_stat=Path.stat;calls=[0]
def changing(path,*args,**kwargs):
 result=original_stat(path,*args,**kwargs)
 if path==large:
  calls[0]+=1
  if calls[0]>1:return SimpleNamespace(st_dev=result.st_dev,st_ino=result.st_ino,st_size=result.st_size,st_mtime_ns=result.st_mtime_ns+1)
 return result
count=c.execute('select count(*) from artifacts').fetchone()[0]
with patch.object(Path,'stat',changing):
 try:streaming.capture(c,large,job=5);raise AssertionError('Changing source accepted')
 except RuntimeError:pass
assert c.execute('select count(*) from artifacts').fetchone()[0]==count and not list((h.ROOT/'raw').glob('.stream-*'));c.close()
client=app.test_client();assert client.get('/').status_code==302
assert client.post('/login',data={'token':'invalid'}).status_code==401
from settings import CONFIG
value=Path(CONFIG['browser_auth_file']).read_text().strip();assert client.post('/login',data={'token':value}).status_code==302
assert client.get('/api/health').status_code==200
Path(CONFIG['browser_auth_file']).write_text('rotated-fixture-credential-longer-than-thirty-two')
assert client.get('/api/health').status_code==401
# Downtime longer than the lookback replays from the durable cursor, not now-48h.
old=dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=10)
(h.ROOT/'state/accounting-cursor.json').write_text(json.dumps({'through_utc':old.isoformat(),'polled_utc':old.isoformat()}))
seen=[]
def query(args,timeout=60):seen.append(args);return b'{"jobs":[]}'
accounting.command=query;accounting.collect();assert seen[0][seen[0].index('--starttime')+1]==(old-dt.timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%S')
saved=json.loads((h.ROOT/'state/accounting-cursor.json').read_text());assert dt.datetime.fromisoformat(saved['through_utc'])<dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=8)
# Failed reads leave the durable cursor unchanged for retry.
previous=saved.copy();previous['polled_utc']=old.isoformat();(h.ROOT/'state/accounting-cursor.json').write_text(json.dumps(previous))
def fail(*args):raise OSError('fixture accounting outage')
accounting.command=fail;accounting.collect();assert json.loads((h.ROOT/'state/accounting-cursor.json').read_text())==previous
# Host queue stays bounded and rotates across all hosts between passes.
live.load_manifests=lambda:[{'job_id':1,'nodes':['fixture-a','fixture-b','fixture-c','fixture-d'],'slurm':{'JobState':'RUNNING'}}]
attempts=[];live.capture_host=lambda job,host:attempts.append(host)
live.run();assert len(attempts)==2;live.run();assert len(attempts)==4 and len(set(attempts))==4
'''
            result=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
