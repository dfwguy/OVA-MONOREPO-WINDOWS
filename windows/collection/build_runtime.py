"""Derive a native runtime from the checked baseline into a NEW external directory."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]


def substitute(text, old, new, expected=1):
    count = text.count(old)
    if count != expected:
        raise ValueError(f'Baseline transform mismatch: expected {expected}, found {count}: {old[:80]}')
    return text.replace(old, new)


def build(source, output, config):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.is_relative_to(REPOSITORY) or output.is_relative_to(source):
        raise ValueError('Build outside the source repository and baseline tree.')
    if output.exists():
        raise ValueError('Output must be a new versioned directory; existing runtime/data are preserved.')
    baseline = json.loads((HERE / 'BASELINE.json').read_text(encoding='utf-8'))
    actual = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()}
    if actual != baseline['files']:
        raise ValueError('Baseline source hashes differ; review/rebase transforms instead of guessing.')
    if not Path(config['root']).is_absolute():
        raise ValueError('Configure an absolute native evidence data root.')
    if not config.get('native_windows_durability_acknowledged', False):
        raise ValueError('Acknowledge the documented Windows file-data/rename durability boundary explicitly.')
    if not 1024 <= int(config['browser_port']) <= 65535:
        raise ValueError('Use an unprivileged browser loopback port.')
    app = output / 'app'
    shutil.copytree(source, app)
    for name in ['native_locking.py', 'native_durable.py', 'generation_pointer.py', 'native_transport.py']:
        shutil.copy2(HERE / name, app / name)
    (app / 'durable.py').write_text('from native_durable import atomic_write, sync_directory, sync_file\n', encoding='utf-8')
    history = (app / 'history.py').read_text(encoding='utf-8')
    history = substitute(history, ' import fcntl', ' import native_locking as fcntl', 3)
    history = substitute(history, '"state/publish.lock","w"', '"state/publish.lock","a+b"')
    history = substitute(history, "'state/scan.lock','w'", "'state/scan.lock','a+b'")
    history = substitute(history, "'state/publish.lock','w'", "'state/publish.lock','a+b'")
    history = substitute(history, "def command(args,timeout=25):return subprocess.run(args,capture_output=True,timeout=timeout,check=True,env=dict(os.environ,TZ='UTC')).stdout", "def command(args,timeout=25):\n from native_transport import command as native_command\n return native_command(args,timeout,CONFIG)")
    history = substitute(history, 'def live_scan(c,capture_stdout=False):\n', "def live_scan(c,capture_stdout=False):\n if not CONFIG.get('native_scheduler_enabled',False):return\n")
    old = "link=ROOT/'lake/current.next';link.unlink(missing_ok=True);link.symlink_to(gen.name);os.replace(link,ROOT/'lake/current');sync_directory(ROOT/'lake');atomic_write(ROOT/'state/health.json',json.dumps(status,indent=2))"
    new = "publish_generation(ROOT/'lake',gen);atomic_write(ROOT/'state/health.json',json.dumps(status,indent=2))"
    history = substitute(history, old, new)
    history = substitute(history, "(ROOT/'app').glob('*.py')", "Path(__file__).resolve().parent.glob('*.py')")
    history = substitute(history, "t.add(ROOT/'app/README.md',arcname='README.md')", "t.add(Path(__file__).resolve().parent/'README.md',arcname='README.md')")
    history = substitute(history, "atomic_write(gen/'manifest.json',json.dumps(status,indent=2))", "status['native_windows']={'scheduler_enabled':bool(CONFIG.get('native_scheduler_enabled',False)),'collector_source_mode':'SSH and configured native mirrors','durability':native_durable.DURABILITY_PROFILE,'site_acceptance':'NOT_COMMISSIONED'}\n atomic_write(gen/'manifest.json',json.dumps(status,indent=2))")
    history = 'import native_durable\nfrom generation_pointer import publish_generation\n' + history
    history = history.replace('os.replace(', 'native_durable.replace_file(')
    (app / 'history.py').write_text(history, encoding='utf-8')
    streaming = (app / 'streaming.py').read_text(encoding='utf-8')
    streaming = 'import native_durable\n' + streaming.replace('os.replace(', 'native_durable.replace_file(')
    (app / 'streaming.py').write_text(streaming, encoding='utf-8')
    browser = (app / 'browser.py').read_text(encoding='utf-8')
    browser = substitute(browser, "gen=(ROOT/'lake/current').resolve()", "gen=resolve_generation(ROOT/'lake')")
    browser = substitute(browser, "c.execute(f\"create table {t} as select * from read_parquet('{gen}/{t}.parquet')\")", "c.read_parquet(str(gen/(t+'.parquet'))).create(t)")
    browser = substitute(browser, r'slurm-history-\d{8}T\d{6}\.tar\.gz', r'slurm-history-\d{8}T\d{6}(?:\d{6})?\.tar\.gz')
    (app / 'browser.py').write_text('from generation_pointer import resolve_generation\n' + browser, encoding='utf-8')
    metadata = (app / 'metadata.py').read_text(encoding='utf-8')
    metadata = substitute(metadata, '    c=db();discover(c);reconcile_manifests(c);live_scan(c,capture_stdout=False);c.commit();c.close()', "    c=db()\n    if CONFIG.get('native_scheduler_enabled',False):discover(c);live_scan(c,capture_stdout=False)\n    reconcile_manifests(c);c.commit();c.close()")
    (app / 'metadata.py').write_text(metadata, encoding='utf-8')
    for file in app.glob('*.py'):
        compile(file.read_text(encoding='utf-8'), str(file), 'exec')
    for name in ['supervisor.py', 'service_wrapper.py']:
        shutil.copy2(HERE / name, output / name)
    (output / 'cluster.json').write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    derived = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(app.iterdir()) if p.is_file()}
    provenance = {'schema_version': 1, 'source_hashes': actual, 'derived_hashes': derived,
                  'adapter_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')},
                  'source_mode': 'native Windows mirrored evidence and optional read-only SSH Slurm queries',
                  'live_site_acceptance': False, 'system_service_installed': False}
    (output / 'runtime-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=REPOSITORY / 'components/OVA_Collection_Framework/source/app')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.source, args.output, json.loads(args.config.read_text(encoding='utf-8-sig'))))
