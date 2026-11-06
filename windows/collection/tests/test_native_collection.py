"""Isolated real-process native collection acceptance. No customer/SSH operations."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import native_locking
from generation_pointer import publish_generation, resolve_generation
from native_durable import atomic_write
from build_runtime import build, REPOSITORY


def lock_probe(path):
    with open(path, 'a+b') as stream:
        try:
            native_locking.flock(stream.fileno(), native_locking.LOCK_EX | native_locking.LOCK_NB)
        except BlockingIOError:
            return 23
    return 0


class NativeCollection(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix='ova-collection-'))
        self.addCleanup(lambda: shutil.rmtree(self.temp, ignore_errors=True))

    def test_actual_crossprocess_lock_and_process_death_release(self):
        path = self.temp / 'writer.lock'
        with path.open('a+b') as stream:
            native_locking.flock(stream.fileno(), native_locking.LOCK_EX)
            child = subprocess.run([sys.executable, '-B', __file__, '--lock-probe', str(path)], capture_output=True, text=True)
            self.assertEqual(child.returncode, 23, child.stdout + child.stderr)
            native_locking.flock(stream.fileno(), native_locking.LOCK_UN)
        code = "import sys;sys.path.insert(0,sys.argv[1]);import native_locking as l;f=open(sys.argv[2],'a+b');l.flock(f.fileno(),l.LOCK_EX);print('LOCKED',flush=True);sys.stdin.read()"
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(HERE), str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'LOCKED')
            self.assertEqual(lock_probe(path), 23)
        finally:
            child.kill()
            child.wait(timeout=15)
            child.stdin.close(); child.stdout.close(); child.stderr.close()
        self.assertEqual(lock_probe(path), 0)

    def test_atomic_generation_pointer_preserves_pinned_readers(self):
        lake = self.temp / 'lake'
        lake.mkdir()
        generations = [lake / 'generation-1', lake / 'generation-2']
        for index, generation in enumerate(generations):
            generation.mkdir()
            atomic_write(generation / 'manifest.json', json.dumps({'fixture': index}))
        publish_generation(lake, generations[0])
        pinned = resolve_generation(lake)
        failures = []
        def writer():
            try:
                for index in range(40):
                    publish_generation(lake, generations[index % 2])
            except Exception as exc:
                failures.append(str(exc))
        thread = threading.Thread(target=writer)
        thread.start()
        for _ in range(100):
            current = resolve_generation(lake)
            self.assertIn(current, generations)
        thread.join(timeout=15)
        self.assertFalse(thread.is_alive())
        self.assertFalse(failures, failures)
        self.assertTrue(pinned.is_dir())
        self.assertFalse((lake / 'current').exists(), 'Native generation pinning must not depend on symlinks.')
        (lake / 'current.json').write_text(json.dumps({'generation': '../escape', 'manifest_sha256': '0'*64}))
        with self.assertRaises(ValueError):
            resolve_generation(lake)

    def test_transport_refuses_mutations_and_disabled_scheduler(self):
        from native_transport import command
        config={'native_scheduler_enabled':True,'scheduler_ssh_alias':'fixture-head'}
        with self.assertRaises(ValueError):
            command(['/usr/bin/scontrol','update','NodeName=fixture','State=DRAIN'],5,config)
        with self.assertRaises(ValueError):
            command(['bash','-c','unexpected'],5,config)
        with self.assertRaises(RuntimeError):
            command(['/usr/bin/scontrol','show','jobs','-o'],5,{'native_scheduler_enabled':False})

    def test_real_ingest_restart_browser_search_and_export(self):
        data, inputs, manifests = [self.temp / name for name in ('data', 'inputs', 'manifests')]
        inputs.mkdir(); manifests.mkdir()
        secret = 'synthetic-sensitive-value-' + secrets.token_hex(8)
        source = inputs / 'job11.out'
        source.write_text('iteration 1/ 10 elapsed time per iteration (ms): 3.5\napi_key=' + secret + '\n')
        (inputs / 'slurmctld.log').write_text('JobId=11 started\n')
        (inputs / 'completions.log').write_text('JobId=11 JobState=COMPLETED Name=synthetic\n')
        (manifests / 'job11.json').write_text(json.dumps({'job_id': 11, 'workload': 'synthetic_native', 'final_state': 'COMPLETED', 'runtime_gate': {'passed': True}}))
        token = secrets.token_hex(32)
        token_path = self.temp / 'browser-credential'
        token_path.write_text(token)
        sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
        config = {'site': 'synthetic', 'cluster': 'synthetic', 'epoch': 'fixture', 'root': str(data),
                  'slurm_bin': '/usr/bin', 'service_user': 'fixture', 'service_group': 'fixture',
                  'controller_log': str(inputs / 'slurmctld.log'), 'completion_log': str(inputs / 'completions.log'),
                  'manifest_dirs': [str(manifests)], 'local_roots': [str(inputs)], 'remote_allowed_roots': [],
                  'browser_port': port, 'browser_auth_file': str(token_path), 'first_job_id': 11,
                  'max_gap_span': 100, 'remote_capture_enabled': False, 'native_scheduler_enabled': False,
                  'native_windows_durability_acknowledged': True, 'browser_secure_cookie': False,
                  'accounting_enabled': False}
        runtime = build(REPOSITORY / 'components/OVA_Collection_Framework/source/app', self.temp / 'runtime', config)
        environment = dict(os.environ, SLURM_HISTORY_CONFIG=str(runtime / 'cluster.json'), PYTHONDONTWRITEBYTECODE='1')
        def run(script, *args):
            result = subprocess.run([sys.executable, '-B', str(runtime / 'app' / script), *args], env=environment, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result
        run('history.py')
        with sqlite3.connect(data / 'state/index.sqlite') as journal:
            self.assertEqual(journal.execute('pragma journal_mode').fetchone()[0], 'wal')
            initial_artifacts = journal.execute('select count(*) from artifacts').fetchone()[0]
            self.assertGreater(initial_artifacts, 0)
            self.assertEqual(journal.execute('select count(*) from metrics').fetchone()[0], 1)
        run('history.py')
        with sqlite3.connect(data / 'state/index.sqlite') as journal:
            self.assertEqual(journal.execute('select count(*) from artifacts').fetchone()[0], initial_artifacts)
        self.assertIn(secret, source.read_text(), 'Original evidence must remain unchanged.')
        for raw in (data / 'raw').rglob('*.gz'):
            self.assertNotIn(secret.encode(), gzip.decompress(raw.read_bytes()))
        run('search_index.py')
        run('history.py', 'export')
        log = (self.temp / 'browser.log').open('wb')
        browser = subprocess.Popen([sys.executable, '-B', str(runtime / 'app/browser.py')], env=environment, stdout=log, stderr=subprocess.STDOUT)
        base = 'http://127.0.0.1:' + str(port)
        def request(path, authenticated=True):
            return urllib.request.urlopen(urllib.request.Request(base + path, headers={'X-Evidence-Token': token} if authenticated else {}), timeout=10)
        try:
            for attempt in range(100):
                try:
                    with request('/api/health') as response:
                        health = json.load(response)
                    break
                except (OSError, urllib.error.URLError):
                    if browser.poll() is not None:
                        self.fail('Browser exited: ' + (self.temp / 'browser.log').read_text())
                    time.sleep(0.1)
            else:
                self.fail('Native browser did not become ready.')
            self.assertEqual(health['native_windows']['site_acceptance'], 'NOT_COMMISSIONED')
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                request('/api/health', authenticated=False)
            self.assertEqual(rejected.exception.code, 401)
            query = urllib.parse.urlencode({'sql': 'select job_id from jobs'})
            with request('/api/query?' + query) as response:
                self.assertEqual(json.load(response)['rows'], [[11]])
            with request('/api/search?' + urllib.parse.urlencode({'q': 'iteration', 'job_id': 11})) as response:
                self.assertGreater(len(json.load(response)['results']), 0)
            with request('/api/exports') as response:
                exports = json.load(response)['files']
            self.assertEqual(len(exports), 1)
            with request('/api/export/' + exports[0]) as response:
                exported = response.read()
            self.assertEqual(hashlib.sha256(exported).hexdigest(), hashlib.sha256((data / 'export' / exports[0]).read_bytes()).hexdigest())
            self.assertFalse((data / 'lake/current').exists())
            self.assertTrue((data / 'lake/current.json').is_file())
        finally:
            browser.terminate()
            browser.wait(timeout=20)
            log.close()
        supervised=subprocess.run([sys.executable,'-B',str(runtime/'supervisor.py'),'--runtime',str(runtime),'--config',str(runtime/'cluster.json'),'--max-seconds','2'],capture_output=True,text=True,timeout=45)
        self.assertEqual(supervised.returncode,0,supervised.stdout+supervised.stderr)
        snapshot=json.loads((data/'state/native-supervisor.json').read_text())
        self.assertEqual(snapshot['status'],'stopped')
        self.assertGreater(snapshot['tasks']['browser']['runs'],0)
        self.assertTrue(all(not task['running'] for task in snapshot['tasks'].values()))


if __name__ == '__main__':
    if '--lock-probe' in sys.argv:
        sys.exit(lock_probe(Path(sys.argv[sys.argv.index('--lock-probe') + 1])))
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--allow-posix', action='store_true')
    args = parser.parse_args()
    if os.name == 'nt' and sys.version_info[:2] != (3,12):
        raise SystemExit('Collection acceptance requires native CPython3.12; the control helper interpreter is separate.')
    if os.name != 'nt' and not args.allow_posix:
        raise SystemExit('Native acceptance requires Windows. --allow-posix runs preparation checks only.')
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NativeCollection)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps({'schema_version': 1, 'platform': sys.platform,
            'python': sys.version, 'native_windows': os.name == 'nt', 'tests_run': result.testsRun,
            'failures': len(result.failures), 'errors': len(result.errors), 'passed': result.wasSuccessful(),
            'scope': 'Synthetic real-process locks, atomic pointers, transport rejection, persistent ingestion, authenticated browser, query/search/export, bounded native supervision',
            'excluded': ['Live customer sources', 'Slurm/VPN commissioning', 'Service installation', 'Reboot/power-loss survival']}, indent=2) + '\n')
    sys.exit(not result.wasSuccessful())
