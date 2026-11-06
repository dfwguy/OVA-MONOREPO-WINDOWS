#!/usr/bin/env python3
"""Fresh Windows-only offline venv and adapter regression checks; no service install."""
import argparse
import datetime
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import build_runtime

HERE = Path(__file__).resolve().parent


def execute(label, argv, cwd, env, logs, checks, timeout=180):
    result = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)
    (logs / (label + '.stdout.log')).write_text(result.stdout, encoding='utf-8')
    (logs / (label + '.stderr.log')).write_text(result.stderr, encoding='utf-8')
    checks[label] = {'exit_code': result.returncode, 'result': 'PASS' if result.returncode == 0 else 'FAIL'}
    if result.returncode:
        raise RuntimeError(label + ' failed; inspect the protected acceptance log directory.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', required=True, type=Path)
    args = parser.parse_args()
    if os.name != 'nt' or sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8:
        raise RuntimeError('Run with native Windows x64 CPython3.12; no Linux runtime result is claimed.')
    root = args.runtime_root.resolve()
    if root.exists() or root == build_runtime.REPO or root.is_relative_to(build_runtime.REPO):
        raise ValueError('Choose a NEW private acceptance directory outside the checkout.')
    root.mkdir(parents=True)
    owner = (os.environ['USERDOMAIN'] + chr(92) if os.environ.get('USERDOMAIN') else '') + os.environ['USERNAME']
    acl = subprocess.run(['icacls', str(root), '/inheritance:r', '/grant:r', owner + ':(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'], capture_output=True, text=True)
    if acl.returncode:
        raise RuntimeError('Cannot protect acceptance directory ACL.')
    logs = root / 'logs'
    logs.mkdir()
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith(('RACK_', 'NVIS_', 'SLURM_', 'GUNICORN_', 'SETTINGS', 'P2P_', 'PYTHON', 'PIP_', 'VIRTUAL_ENV', 'CONDA_'))}
    env.update(PYTHONDONTWRITEBYTECODE='1', PIP_NO_INDEX='1', PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK='1', NVIS_VAR_DIR=str(root / 'private-state'), NVIS_RACKSTATUS_CONFIG=str(root / 'nonexistent-private-site.toml'))
    checks = {}
    report = {'profile': 'fresh-native-rack-p2p-offline-adapters', 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'python_version': sys.version, 'checks': checks, 'customer_cluster_contacted': False, 'services_installed_or_changed': False, 'native_p2p_manager_core_tested': False, 'live_pythoncm_execution_qualified': False}
    try:
        built = build_runtime.build(root / 'source')
        for name, lock in [('rack', 'requirements-rack-cp312-win_amd64.lock'), ('p2p', 'requirements-p2p-cp312-win_amd64.lock')]:
            venv = root / (name + '-venv')
            execute(name + '-create-venv', [sys.executable, '-m', 'venv', str(venv)], root, env, logs, checks)
            python = venv / 'Scripts/python.exe'
            execute(name + '-offline-install', [str(python), '-m', 'pip', 'install', '--no-index', '--find-links', str(HERE / 'wheelhouse'), '--require-hashes', '--only-binary=:all:', '-r', str(HERE / lock)], root, env, logs, checks, timeout=300)
            execute(name + '-pip-check', [str(python), '-m', 'pip', 'check'], root, env, logs, checks)
        rack = built / 'rack-status'
        rack_python = root / 'rack-venv/Scripts/python.exe'
        rack_env = {**env, 'PYTHONPATH': str(rack / 'backend') + os.pathsep + str(rack)}
        for label, command, timeout in [
            ('rack-kernel-file-locks', ['-m', 'unittest', 'discover', '-s', 'backend/tests', '-p', 'test_file_lock.py', '-v'], 90),
            ('rack-native-tls-websocket', ['-m', 'unittest', 'windows.test_server', '-v'], 180),
            ('rack-native-conpty', ['-m', 'unittest', 'discover', '-s', 'backend/tests', '-p', 'test_windows_terminal.py', '-v'], 90),
        ]:
            execute(label, [str(rack_python), *command], rack, rack_env, logs, checks, timeout=timeout)
        execute('pythoncm-fail-closed-workflow-boundary', [str(rack_python), '-m', 'unittest', 'discover', '-s', str(HERE / 'tests'), '-v'], root, env, logs, checks)
        p2p = built / 'p2p-console/windows-control'
        execute('p2p-console-loopback-mock-manager', [str(root / 'p2p-venv/Scripts/python.exe'), str(p2p / 'test_console.py'), '-v'], p2p, env, logs, checks)
        report['status'] = 'PASS_FRESH_NATIVE_OFFLINE_ADAPTER_CHECKS'
    except Exception as error:
        report['status'] = 'FAIL'
        report['error'] = str(error)
    finally:
        report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        report['limits'] = ['Native TLS/WebSocket fixture and local ConPTY checks are not customer login/SSH/head-terminal acceptance.', 'P2P tests use a loopback mock Manager; actual Manager/scheduler/seed/database core remains Linux.', 'PythonCM workflow submission is intentionally blocked until its explicit job fields and real execution-session lifecycle are qualified.']
        (root / 'acceptance-result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS_FRESH_NATIVE_OFFLINE_ADAPTER_CHECKS' else 1


if __name__ == '__main__':
    sys.exit(main())
