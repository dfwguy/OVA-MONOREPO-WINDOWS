#!/usr/bin/env python3
"""Pinned native Windows observability evaluation core; Python standard library only."""
import argparse
import base64
import contextlib
import ctypes
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import signal
import stat
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
REPO = next((parent for parent in HERE.parents if (parent / 'control').is_dir() and (parent / 'components').is_dir()), HERE)


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def dependency_manifest():
    return json.loads((HERE / 'DEPENDENCIES.json').read_text(encoding='utf-8'))


def verify_dependencies():
    manifest = dependency_manifest()
    for item in manifest['assets']:
        path = HERE / 'dependencies' / item['filename']
        if not path.is_file() or sha256(path) != item['sha256']:
            raise ValueError('Missing or modified dependency: ' + item['filename'])
    return manifest


def require_windows():
    if os.name != 'nt':
        raise RuntimeError('Native runtime requires Windows x64; no Linux fallback is provided.')
    if struct.calcsize('P') != 8:
        raise RuntimeError('Use 64-bit Python on Windows x64.')


def outside_repo(value):
    path = Path(value).resolve()
    if path == REPO or path.is_relative_to(REPO):
        raise ValueError('Runtime data/evidence must be outside the source repository.')
    return path


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def unzip(archive, destination):
    with zipfile.ZipFile(archive) as z:
        seen = set()
        total = 0
        for info in z.infolist():
            raw_name = info.orig_filename
            if raw_name != info.filename or '\\' in raw_name or '\x00' in raw_name:
                raise ValueError('ZIP path normalization is forbidden')
            p = PurePosixPath(raw_name)
            mode = info.external_attr >> 16
            if p.is_absolute() or '..' in p.parts or '\\' in info.filename or ':' in info.filename or stat.S_ISLNK(mode):
                raise ValueError('Unsafe archive member')
            key = info.filename.casefold()
            if key in seen:
                raise ValueError('Duplicate archive member')
            seen.add(key)
            total += info.file_size
        if total > 3_000_000_000:
            raise ValueError('Unexpected dependency expansion size')
        z.extractall(destination)


def ports(base):
    if not 1024 <= base <= 65520:
        raise ValueError('Port base must be in 1024..65520')
    return dict(zip(['grafana', 'prometheus', 'loki', 'loki_grpc', 'alloy', 'logs', 'metrics'], range(base + 1, base + 8)))


def prepare(root, base):
    require_windows()
    manifest = verify_dependencies()
    if root.exists():
        raise ValueError('Choose a NEW runtime directory; preparation never overwrites existing state.')
    p = ports(base)
    root.mkdir(parents=True)
    owner = (os.environ['USERDOMAIN'] + chr(92) if os.environ.get('USERDOMAIN') else '') + os.environ['USERNAME']
    acl = subprocess.run(['icacls', str(root), '/inheritance:r', '/grant:r', owner + ':(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'], capture_output=True, text=True)
    if acl.returncode:
        raise RuntimeError('Cannot protect the new runtime directory ACL: ' + acl.stderr)
    for name in ['config', 'logs', 'data', 'config/targets', 'config/provisioning/datasources', 'config/provisioning/dashboards', 'config/dashboards']:
        (root / name).mkdir(parents=True, exist_ok=True)
    executables = {}
    for item in manifest['assets']:
        destination = root / 'bin' / item['component']
        unzip(HERE / 'dependencies' / item['filename'], destination)
        matches = list(destination.glob(item['entrypoint_glob']))
        if len(matches) != 1:
            raise ValueError('Cannot uniquely resolve ' + item['component'] + ' executable')
        exe = matches[0]
        executables[item['component']] = {'path': str(exe), 'sha256': sha256(exe)}
    config = root / 'config'
    prom = f'''global:
  scrape_interval: 5s
  evaluation_interval: 15s
scrape_configs:
  - job_name: native-observability
    static_configs:
      - targets: ["127.0.0.1:{p['prometheus']}", "127.0.0.1:{p['loki']}", "127.0.0.1:{p['alloy']}", "127.0.0.1:{p['grafana']}"]
  - job_name: approved-cluster-exporters
    file_sd_configs:
      - files: ["{(config / 'targets' / 'cluster.json').as_posix()}"]
'''
    (config / 'prometheus.yml').write_text(prom, encoding='utf-8')
    write_json(config / 'targets' / 'cluster.json', [])
    loki_root = (root / 'data' / 'loki').as_posix()
    loki = f'''auth_enabled: false
server:
  http_listen_address: 127.0.0.1
  http_listen_port: {p['loki']}
  grpc_listen_address: 127.0.0.1
  grpc_listen_port: {p['loki_grpc']}
common:
  instance_addr: 127.0.0.1
  path_prefix: "{loki_root}"
  storage:
    filesystem:
      chunks_directory: "{loki_root}/chunks"
      rules_directory: "{loki_root}/rules"
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory
schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h
storage_config:
  tsdb_shipper:
    active_index_directory: "{loki_root}/index"
    cache_location: "{loki_root}/index-cache"
ingester:
  wal:
    dir: "{loki_root}/wal"
limits_config:
  retention_period: 168h
  allow_structured_metadata: true
compactor:
  working_directory: "{loki_root}/compactor"
  retention_enabled: true
  delete_request_store: filesystem
'''
    (config / 'loki.yaml').write_text(loki, encoding='utf-8')
    alloy = f'''logging {{
  level = "info"
}}
prometheus.receive_http "gateway" {{
  http {{
    listen_address = "127.0.0.1"
    listen_port = {p['metrics']}
  }}
  forward_to = [prometheus.remote_write.local.receiver]
}}
prometheus.remote_write "local" {{
  endpoint {{
    url = "http://127.0.0.1:{p['prometheus']}/api/v1/write"
  }}
}}
loki.source.api "gateway" {{
  http {{
    listen_address = "127.0.0.1"
    listen_port = {p['logs']}
  }}
  forward_to = [loki.write.local.receiver]
}}
loki.write "local" {{
  endpoint {{
    url = "http://127.0.0.1:{p['loki']}/loki/api/v1/push"
  }}
}}
'''
    (config / 'config.alloy').write_text(alloy, encoding='utf-8')
    grafana = f'''[server]
http_addr = 127.0.0.1
http_port = {p['grafana']}
domain = localhost
[paths]
data = {(root / 'data' / 'grafana').as_posix()}
logs = {(root / 'logs' / 'grafana').as_posix()}
plugins = {(root / 'data' / 'grafana-plugins').as_posix()}
provisioning = {(config / 'provisioning').as_posix()}
[analytics]
reporting_enabled = false
check_for_updates = false
check_for_plugin_updates = false
[auth.anonymous]
enabled = false
[security]
admin_user = ova-admin
cookie_samesite = strict
[users]
allow_sign_up = false
[plugins]
plugin_admin_enabled = false
'''
    (config / 'grafana.ini').write_text(grafana, encoding='utf-8')
    sources = 'apiVersion: 1\ndatasources:\n'
    for name, uid, typ, port, default in [('Prometheus', 'nvis-prometheus', 'prometheus', p['prometheus'], True), ('Metrics compatibility alias', 'nvis-victoriametrics', 'prometheus', p['prometheus'], False), ('OTEL metrics compatibility alias', 'nvis-otel-victoriametrics', 'prometheus', p['prometheus'], False), ('Loki', 'nvis-loki', 'loki', p['loki'], False)]:
        sources += f'  - name: {name}\n    uid: {uid}\n    type: {typ}\n    access: proxy\n    url: http://127.0.0.1:{port}\n    isDefault: {str(default).lower()}\n    editable: false\n'
    (config / 'provisioning/datasources/native.yaml').write_text(sources, encoding='utf-8')
    dashboards = f'''apiVersion: 1
providers:
  - name: native-core
    orgId: 1
    type: file
    disableDeletion: true
    options:
      path: "{(config / 'dashboards').as_posix()}"
'''
    (config / 'provisioning/dashboards/native.yaml').write_text(dashboards, encoding='utf-8')
    dashboard = {'id': None, 'uid': 'ova-native-core', 'title': 'OVA Native Windows Core', 'schemaVersion': 39, 'version': 1, 'refresh': '10s', 'panels': [{'id': 1, 'title': 'Native service scrape health', 'type': 'timeseries', 'gridPos': {'x': 0, 'y': 0, 'w': 24, 'h': 9}, 'datasource': {'type': 'prometheus', 'uid': 'nvis-prometheus'}, 'targets': [{'refId': 'A', 'expr': 'up{job="native-observability"}', 'legendFormat': '{{instance}}'}]}]}
    write_json(config / 'dashboards/native-core.json', dashboard)
    profile = {'schema_version': 1, 'runtime_root': str(root), 'port_base': base, 'ports': p, 'executables': executables, 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'production_commissioned': False}
    write_json(root / 'profile.json', profile)
    return profile


def load_profile(root):
    profile = json.loads((root / 'profile.json').read_text(encoding='utf-8'))
    if Path(profile['runtime_root']).resolve() != root:
        raise ValueError('Runtime profile path mismatch')
    for item in profile['executables'].values():
        path = Path(item['path']).resolve()
        if not path.is_relative_to(root / 'bin') or sha256(path) != item['sha256']:
            raise ValueError('Runtime binary path/hash mismatch')
    return profile


def identity(pid):
    # Read the Windows kernel creation timestamp and executable path before stopping a PID.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    try:
        creation, exit_time, kernel_time, user_time = (ctypes.c_ulonglong() for _ in range(4))
        if not kernel.GetProcessTimes(ctypes.c_void_p(handle), ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            return None
        if exit_time.value:
            return None
        size = ctypes.c_ulong(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(ctypes.c_void_p(handle), 0, buffer, ctypes.byref(size)):
            return None
        return {'pid': int(pid), 'created': creation.value, 'path': str(Path(buffer.value).resolve())}
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))


def request(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=5) as response:
        body = response.read()
        return response.status, body


def wait_until(predicate, timeout=90):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            value = predicate()
            if value:
                return value
        except (OSError, ValueError, KeyError, urllib.error.URLError) as exc:
            last = str(exc)
        time.sleep(1)
    raise RuntimeError('Timed out waiting for native readiness: ' + str(last))


def start(root, base):
    require_windows()
    if not (root / 'profile.json').exists():
        profile = prepare(root, base)
    else:
        profile = load_profile(root)
    password = os.environ.get('OVA_OBS_ADMIN_PASSWORD', '')
    if password and len(password) < 16:
        raise ValueError('OVA_OBS_ADMIN_PASSWORD must have at least 16 characters.')
    if not password and not (root / 'data/grafana/grafana.db').is_file():
        raise ValueError('Initial bootstrap requires OVA_OBS_ADMIN_PASSWORD of at least 16 characters; it is passed only in child environment.')
    if (root / 'processes.json').exists():
        raise ValueError('Existing ownership state: run stop before starting this profile again.')
    p = profile['ports']
    import socket
    for port in p.values():
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError as exc:
                raise RuntimeError('Port already used; refusing to interfere: ' + str(port)) from exc
    exe = {name: item['path'] for name, item in profile['executables'].items()}
    configs = root / 'config'
    checks = [[str(Path(exe['prometheus']).with_name('promtool.exe')), 'check', 'config', str(configs / 'prometheus.yml')], [exe['loki'], '-config.file=' + str(configs / 'loki.yaml'), '-verify-config=true'], [exe['alloy'], 'fmt', str(configs / 'config.alloy')]]
    for command in checks:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError('Native configuration check failed for ' + Path(command[0]).name + ': ' + (result.stderr + result.stdout)[-4000:])
    commands = {
        'prometheus': [exe['prometheus'], '--config.file=' + str(configs / 'prometheus.yml'), '--storage.tsdb.path=' + str(root / 'data/prometheus'), '--storage.tsdb.retention.time=2d', '--web.listen-address=127.0.0.1:' + str(p['prometheus']), '--web.enable-remote-write-receiver'],
        'loki': [exe['loki'], '-config.file=' + str(configs / 'loki.yaml')],
        'alloy': [exe['alloy'], 'run', str(configs / 'config.alloy'), '--server.http.listen-addr=127.0.0.1:' + str(p['alloy']), '--storage.path=' + str(root / 'data/alloy'), '--disable-reporting'],
        'grafana': [exe['grafana'], '--homepath=' + str(Path(exe['grafana']).parent.parent), '--config=' + str(configs / 'grafana.ini')],
    }
    state = {'processes': [], 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    write_json(root / 'processes.json', state)
    try:
        for name in ['prometheus', 'loki', 'alloy', 'grafana']:
            env = os.environ.copy()
            env.pop('OVA_OBS_ADMIN_PASSWORD', None)
            if name == 'grafana' and password:
                env['GF_SECURITY_ADMIN_PASSWORD'] = password
            with (root / 'logs' / (name + '.stdout.log')).open('ab') as stdout, (root / 'logs' / (name + '.stderr.log')).open('ab') as stderr:
                child = subprocess.Popen(commands[name], cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            owned = wait_until(lambda: identity(child.pid), timeout=10)
            state['processes'].append({'component': name, **owned})
            write_json(root / 'processes.json', state)
        for component, path in [('prometheus', '/-/ready'), ('loki', '/ready'), ('alloy', '/-/ready'), ('grafana', '/api/health')]:
            wait_until(lambda name=component, endpoint=path: request('http://127.0.0.1:' + str(p[name]) + endpoint)[0] == 200)
        return profile
    except Exception:
        stop(root)
        raise


def stop(root):
    require_windows()
    state_path = root / 'processes.json'
    if not state_path.exists():
        return []
    state = json.loads(state_path.read_text(encoding='utf-8'))
    results = []
    for proc in reversed(state['processes']):
        current = identity(proc['pid'])
        expected = {key: proc[key] for key in ['pid', 'created', 'path']}
        if current is None:
            results.append({'component': proc['component'], 'status': 'already_exited'})
            continue
        if current != expected or not Path(current['path']).is_relative_to(root / 'bin'):
            raise RuntimeError('Process identity changed; refusing to stop PID ' + str(proc['pid']))
        graceful = False
        try:
            os.kill(proc['pid'], signal.CTRL_BREAK_EVENT)
            for _ in range(50):
                time.sleep(0.1)
                if identity(proc['pid']) is None:
                    graceful = True
                    break
        except OSError:
            pass
        if not graceful:
            if identity(proc['pid']) != expected:
                raise RuntimeError('Process identity changed before termination')
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(0x0001 | 0x1000, False, proc['pid'])
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not kernel.TerminateProcess(ctypes.c_void_p(handle), 1):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                kernel.CloseHandle(ctypes.c_void_p(handle))
            wait_until(lambda: identity(proc['pid']) is None, timeout=10)
        results.append({'component': proc['component'], 'status': 'stopped', 'graceful_control_break': graceful, 'forced_fallback': not graceful})
    state_path.unlink()
    return results


def serve(root, base):
    running = True
    def request_stop(_signum, _frame):
        nonlocal running
        running = False
    for signum in [signal.SIGINT, signal.SIGTERM, signal.SIGBREAK]:
        signal.signal(signum, request_stop)
    try:
        start(root, base)
        while running:
            state = json.loads((root / 'processes.json').read_text(encoding='utf-8'))
            for proc in state['processes']:
                expected = {key: proc[key] for key in ['pid', 'created', 'path']}
                if identity(proc['pid']) != expected:
                    raise RuntimeError('A supervised native component exited: ' + proc['component'])
            time.sleep(1)
    finally:
        stop(root)


def varint(number):
    result = bytearray()
    while number > 127:
        result.append((number & 127) | 128)
        number >>= 7
    result.append(number)
    return bytes(result)


def field(number, data):
    return varint(number * 8 + 2) + varint(len(data)) + data


def remote_write_canary():
    labels = [('__name__', 'ova_windows_native_canary'), ('profile', 'isolated')]
    series = b''.join(field(1, field(1, key.encode()) + field(2, value.encode())) for key, value in labels)
    series += field(2, b'\x09' + struct.pack('<d', 1.0) + b'\x10' + varint(int(time.time() * 1000)))
    raw = field(1, series)
    length = len(raw) - 1
    nbytes = max(1, (length.bit_length() + 7) // 8)
    tag = bytes([length << 2]) if length < 60 else bytes([(59 + nbytes) << 2]) + length.to_bytes(nbytes, 'little')
    return varint(len(raw)) + tag + raw


def acceptance(root, base, report):
    require_windows()
    if root.exists():
        raise ValueError('Acceptance requires a NEW isolated runtime directory; existing instances are untouched.')
    os.environ['OVA_OBS_ADMIN_PASSWORD'] = secrets.token_urlsafe(32)
    result = {'profile': 'native-windows-isolated-core', 'production_commissioned': False, 'customer_cluster_contacted': False, 'checks': {}, 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        profile = start(root, base)
        p = profile['ports']
        result['ports'] = p
        result['checks']['four_process_readiness'] = 'PASS'
        auth = {'Authorization': 'Basic ' + base64.b64encode(('ova-admin:' + os.environ['OVA_OBS_ADMIN_PASSWORD']).encode()).decode()}
        status, body = request(f"http://127.0.0.1:{p['grafana']}/api/org", headers=auth)
        if status != 200:
            raise RuntimeError('Grafana authentication failed')
        result['checks']['grafana_authenticated_api'] = 'PASS'
        request(f"http://127.0.0.1:{p['metrics']}/api/v1/metrics/write", remote_write_canary(), {'Content-Type': 'application/x-protobuf', 'Content-Encoding': 'snappy', 'X-Prometheus-Remote-Write-Version': '0.1.0'})
        def metric_present():
            _, body = request(f"http://127.0.0.1:{p['prometheus']}/api/v1/query?" + urllib.parse.urlencode({'query': 'ova_windows_native_canary{profile="isolated"}'}))
            return bool(json.loads(body)['data']['result'])
        wait_until(metric_present)
        result['checks']['alloy_to_prometheus_remote_write_query'] = 'PASS'
        marker = 'ova-native-canary-' + secrets.token_hex(8)
        marker_ns = time.time_ns()
        payload = json.dumps({'streams': [{'stream': {'job': 'ova-native-canary'}, 'values': [[str(marker_ns), marker]]}]}).encode()
        request(f"http://127.0.0.1:{p['logs']}/loki/api/v1/push", payload, {'Content-Type': 'application/json'})
        def log_present():
            query = urllib.parse.urlencode({'query': '{job="ova-native-canary"}', 'start': str(marker_ns - 60_000_000_000), 'end': str(time.time_ns()), 'limit': '20'})
            _, body = request(f"http://127.0.0.1:{p['loki']}/loki/api/v1/query_range?" + query)
            return marker in body.decode()
        wait_until(log_present)
        result['checks']['alloy_to_loki_ingest_query'] = 'PASS'
        _, body = request(f"http://127.0.0.1:{p['grafana']}/api/dashboards/uid/ova-native-core", headers=auth)
        if json.loads(body)['dashboard']['uid'] != 'ova-native-core':
            raise RuntimeError('Native dashboard provisioning failed')
        result['checks']['grafana_dashboard_provisioning'] = 'PASS'
        for uid in ['nvis-prometheus', 'nvis-loki']:
            _, body = request(f"http://127.0.0.1:{p['grafana']}/api/datasources/uid/{uid}/health", headers=auth)
            if json.loads(body).get('status') != 'OK':
                raise RuntimeError('Grafana datasource health failed: ' + uid)
        result['checks']['grafana_live_datasource_health'] = 'PASS'
        result['restart_cleanup'] = stop(root)
        start(root, base)
        wait_until(metric_present)
        wait_until(log_present)
        request(f"http://127.0.0.1:{p['grafana']}/api/org", headers=auth)
        result['checks']['restart_persisted_metrics_logs_and_grafana_identity'] = 'PASS'
        result['status'] = 'PASS_ISOLATED_NATIVE_CORE'
    except Exception as exc:
        result['status'] = 'FAIL'
        result['error'] = str(exc)
    finally:
        try:
            result['cleanup'] = stop(root)
        except Exception as exc:
            result['cleanup_error'] = str(exc)
            result['status'] = 'FAIL'
        os.environ.pop('OVA_OBS_ADMIN_PASSWORD', None)
        result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        report.parent.mkdir(parents=True, exist_ok=True)
        write_json(report, result)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS_ISOLATED_NATIVE_CORE' else 1


@contextlib.contextmanager
def operation_lock(root):
    root.parent.mkdir(parents=True, exist_ok=True)
    lock = root.parent / ('.' + root.name + '.ova-observability-operation.lock')
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise RuntimeError('Another profile operation or stale operation lock exists: ' + str(lock)) from exc
    try:
        yield
    finally:
        lock.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['verify', 'prepare', 'start', 'serve', 'stop', 'acceptance'])
    parser.add_argument('--runtime-root', type=outside_repo)
    parser.add_argument('--port-base', type=int, default=18000)
    parser.add_argument('--report', type=outside_repo)
    args = parser.parse_args()
    if args.action == 'verify':
        manifest = verify_dependencies()
        print('PASS: ' + str(len(manifest['assets'])) + ' publisher-pinned native Windows dependency archives')
        return 0
    if args.runtime_root is None:
        parser.error('--runtime-root is required')
    require_windows()
    with operation_lock(args.runtime_root):
        if args.action == 'acceptance':
            if args.report is None:
                parser.error('--report is required for acceptance')
            return acceptance(args.runtime_root, args.port_base, args.report)
        if args.action == 'prepare':
            prepare(args.runtime_root, args.port_base)
        elif args.action == 'serve':
            serve(args.runtime_root, args.port_base)
        elif args.action == 'start':
            profile = start(args.runtime_root, args.port_base)
            print('Native core started on loopback; Grafana http://127.0.0.1:' + str(profile['ports']['grafana']))
        else:
            print(json.dumps(stop(args.runtime_root), indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
        sys.exit(1)
