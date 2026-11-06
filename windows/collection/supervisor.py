"""Native process/timer supervisor, intended to run under the existing WinSW service."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time


def supervise(runtime, config_path, max_seconds=None):
    runtime = Path(runtime).resolve()
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text())
    root = Path(config['root'])
    state = root / 'state'
    logs = root / 'logs'
    state.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(runtime / 'app'))
    from native_durable import atomic_write
    import native_locking
    owner = open(state / 'native-supervisor.lock', 'a+b')
    native_locking.flock(owner.fileno(), native_locking.LOCK_EX | native_locking.LOCK_NB)
    stop = threading.Event()
    for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stop.set())
    definitions = {'scan': ('history.py', 60, 600), 'live': ('live.py', 15, 180),
                   'backfill': ('backfill_remote.py', 120, 180), 'search': ('search_index.py', 5, 120),
                   'browser': ('browser.py', 5, None)}
    if config.get('native_scheduler_enabled', False):
        definitions['metadata'] = ('metadata.py', 15, 60)
    tasks = {name: {'process': None, 'last_exit': None, 'next_run': 0, 'restarts': 0} for name in definitions}
    environment = dict(os.environ, SLURM_HISTORY_CONFIG=str(config_path), PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    started = time.monotonic()
    try:
        while not stop.is_set():
            tick = time.monotonic()
            for name, (script, interval, timeout) in definitions.items():
                task = tasks[name]
                process = task['process']
                if process is not None:
                    code = process.poll()
                    if code is None and timeout is not None and tick - task['started'] > timeout:
                        process.kill()
                        code = process.wait(timeout=10)
                        task['timed_out'] = True
                    if code is None:
                        continue
                    task['last_exit'] = code
                    task['process'] = None
                    task['log_handle'].close()
                    task['next_run'] = tick + interval
                # Publish an initial lake before starting browser/search readers.
                if name in ('browser', 'search') and not (root / 'lake/current.json').exists():
                    continue
                if tick >= task['next_run']:
                    log = logs / (name + '.log')
                    if log.exists() and log.stat().st_size > 5 * 1024 * 1024:
                        backup = log.with_suffix('.previous.log')
                        backup.unlink(missing_ok=True)
                        log.replace(backup)
                    handle = log.open('ab', buffering=0)
                    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
                    task['process'] = subprocess.Popen([sys.executable, '-B', str(runtime / 'app' / script)],
                        cwd=runtime / 'app', env=environment, stdout=handle, stderr=subprocess.STDOUT, creationflags=flags)
                    task.update(started=tick, log_handle=handle, restarts=task['restarts'] + 1, timed_out=False)
            report = {'schema_version': 1, 'updated_utc': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
                      'pid': os.getpid(), 'site_acceptance': 'NOT_COMMISSIONED',
                      'scheduler_enabled': bool(config.get('native_scheduler_enabled', False)),
                      'tasks': {name: {'pid': task['process'].pid if task['process'] else None,
                                'last_exit': task['last_exit'], 'runs': task['restarts'],
                                'timed_out': task.get('timed_out', False)} for name, task in tasks.items()}}
            atomic_write(state / 'native-supervisor.json', json.dumps(report, indent=2))
            if max_seconds is not None and tick - started >= max_seconds:
                break
            stop.wait(1)
    finally:
        for task in tasks.values():
            process = task['process']
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            if task.get('log_handle') and not task['log_handle'].closed:
                task['log_handle'].close()
        atomic_write(state / 'native-supervisor.json', json.dumps({'schema_version':1, 'status':'stopped', 'pid':os.getpid(), 'site_acceptance':'NOT_COMMISSIONED', 'tasks':{name:{'running':False,'last_exit':task['process'].poll() if task['process'] else task['last_exit'],'runs':task['restarts']} for name,task in tasks.items()}}, indent=2))
        owner.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--max-seconds', type=float)
    options = parser.parse_args()
    supervise(options.runtime, options.config, options.max_seconds)
