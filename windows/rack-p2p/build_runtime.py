#!/usr/bin/env python3
"""Verify and assemble fresh Rack Windows/P2P-console source; never install services."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ADAPTERS = HERE / 'adapters'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def safe_member(root, relative):
    rel = PurePosixPath(relative)
    if rel.is_absolute() or '..' in rel.parts or '\\' in relative or ':' in relative:
        raise ValueError('Unsafe manifest path: ' + relative)
    path = root.joinpath(*rel.parts)
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Unsafe manifest source: ' + relative)
    return path


def verify_hash(path, expected):
    if not path.is_file() or digest(path) != expected:
        raise ValueError('Missing or modified input: ' + str(path))


def verify_adapters(contract):
    verify_hash(ADAPTERS / 'MANIFEST.json', contract['adapter_manifest_sha256'])
    manifest = load(ADAPTERS / 'MANIFEST.json')
    listed = set()
    for entry in manifest['files']:
        path = safe_member(ADAPTERS, entry['path'])
        if entry['path'] in listed:
            raise ValueError('Duplicate adapter member')
        listed.add(entry['path'])
        verify_hash(path, entry['export_sha256'])
        if path.stat().st_size != entry['bytes']:
            raise ValueError('Adapter byte count mismatch')
    actual = {p.relative_to(ADAPTERS).as_posix() for p in ADAPTERS.rglob('*') if p.is_file()}
    if actual != listed | {'MANIFEST.json'}:
        raise ValueError('Unlisted or missing adapter payload')
    return manifest


def forbidden_runtime_file(relative):
    parts = PurePosixPath(relative).parts
    if '__pycache__' in parts or relative.endswith('.pyc'):
        return True
    if relative == '.env' or relative.startswith(('var/secrets/', 'var/state/', 'var/cache/')):
        return True
    if relative.startswith('var/logs/') and Path(relative).name != '.gitkeep':
        return True
    return False


def source_entries(kit, prefix, expected_manifest_hash):
    verify_hash(kit / 'FILE_MANIFEST.json', expected_manifest_hash)
    entries = []
    for entry in load(kit / 'FILE_MANIFEST.json')['files']:
        if not entry['path'].startswith(prefix):
            continue
        relative = entry['path'][len(prefix):]
        if forbidden_runtime_file(relative):
            raise ValueError('Runtime state is forbidden in the base source: ' + relative)
        path = safe_member(kit, entry['path'])
        verify_hash(path, entry['sha256'])
        if path.stat().st_size != entry['bytes']:
            raise ValueError('Base byte count mismatch: ' + entry['path'])
        entries.append((relative, path, entry.get('mode')))
    return entries


def guard_workflow(text, patch):
    if hashlib.sha256(text.encode()).hexdigest() != patch['before_sha256']:
        raise ValueError('Workflow guard preimage mismatch')
    if text.count(patch['anchor']) != 1:
        raise ValueError('Workflow guard anchor is not unique')
    updated = text.replace(patch['anchor'], patch['replacement'])
    if hashlib.sha256(updated.encode()).hexdigest() != patch['after_sha256']:
        raise ValueError('Workflow guard result mismatch')
    return updated


def verified_inputs():
    contract = load(HERE / 'BUILD_CONTRACT.json')
    adapters = verify_adapters(contract)
    verify_hash(HERE / 'patches/pythoncm-workflow-guard.json', contract['guard_patch_sha256'])
    verify_hash(HERE / 'patches/pythoncm-workflow-guard.patch', contract['guard_readable_diff_sha256'])
    verify_hash(HERE / 'patches/native-tls-test-normal-close.json', contract['tls_test_patch_sha256'])
    verify_hash(HERE / 'patches/native-tls-test-normal-close.patch', contract['tls_test_readable_diff_sha256'])
    verify_hash(HERE / 'requirements-rack-cp312-win_amd64.lock', contract['rack_lock_sha256'])
    verify_hash(HERE / 'requirements-p2p-cp312-win_amd64.lock', contract['p2p_lock_sha256'])
    verify_hash(HERE / 'WHEELHOUSE.json', contract['wheelhouse_manifest_sha256'])
    rack_kit = REPO / 'components/nvis-rack-status'
    rack_entries = source_entries(rack_kit, 'source/', contract['rack_component_manifest_sha256'])
    p2p_entries = source_entries(REPO / 'components/nvis-p2p', 'console-static/', contract['p2p_component_manifest_sha256'])
    expected = {entry['path'][7:] for entry in load(rack_kit / 'FILE_MANIFEST.json')['files'] if entry['path'].startswith('source/')}
    actual = {p.relative_to(rack_kit / 'source').as_posix() for p in (rack_kit / 'source').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    if expected != actual:
        raise ValueError('Rack source has unlisted or missing files; no installed state is copied.')
    for entry in adapters['files']:
        prefix = 'rack-status/overlay/'
        if entry['path'].startswith(prefix) and entry.get('base_sha256'):
            verify_hash(safe_member(rack_kit / 'source', entry['path'][len(prefix):]), entry['base_sha256'])
    wheels = load(HERE / 'WHEELHOUSE.json')
    if wheels['dependency_metadata_closure_issues']:
        raise ValueError('Windows dependency closure has unresolved requirements')
    for item in wheels['assets']:
        verify_hash(safe_member(HERE / 'wheelhouse', item['filename']), item['sha256'])
    if {p.name for p in (HERE / 'wheelhouse').glob('*.whl')} != {item['filename'] for item in wheels['assets']}:
        raise ValueError('Unlisted or missing wheelhouse asset')
    return contract, adapters, rack_entries, p2p_entries


def copy_file(source, target, mode=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if mode and os.name == 'posix':
        target.chmod(int(mode, 8))


def build(destination):
    destination = destination.resolve()
    if destination == REPO or destination.is_relative_to(REPO):
        raise ValueError('Build outside the source repository.')
    if destination.exists():
        raise ValueError('Choose a fresh versioned destination; no existing installation is overwritten.')
    contract, adapters, rack, console = verified_inputs()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + destination.name + '-build-', dir=destination.parent))
    try:
        for relative, source, mode in rack:
            copy_file(source, staging / 'rack-status' / relative, mode)
        for relative, source, mode in console:
            copy_file(source, staging / 'p2p-console/console-static' / relative, mode)
        for entry in adapters['files']:
            relative = entry['path']
            if relative.startswith('rack-status/overlay/'):
                target = staging / 'rack-status' / relative[len('rack-status/overlay/'):]
            elif relative.startswith('p2p/windows-control/'):
                target = staging / 'p2p-console/windows-control' / relative[len('p2p/windows-control/'):]
            elif relative.startswith('examples/'):
                target = staging / 'config-examples' / relative[len('examples/'):]
            else:
                continue
            copy_file(ADAPTERS / relative, target, entry.get('unix_mode'))
        for patch_name in ['pythoncm-workflow-guard.json', 'native-tls-test-normal-close.json']:
            source_patch = load(HERE / 'patches' / patch_name)
            target = staging / 'rack-status' / source_patch['source_path']
            target.write_text(guard_workflow(target.read_text(encoding='utf-8'), source_patch), encoding='utf-8', newline='\n')
        patch = load(HERE / 'patches/pythoncm-workflow-guard.json')
        capabilities = {'native_rack_web_runtime': 'SOURCE_ASSEMBLED; actual host acceptance required', 'pythoncm_inventory': 'Separate read-only capability; actual configured head/session required', 'pythoncm_workflow_execution': 'DISABLED_FAIL_CLOSED_BEFORE_SUBMIT', 'reason': patch['reason'], 'slurm_workflow_provider': 'Preserved source behavior; real cluster qualification remains required', 'p2p_windows': 'Console/proxy only; no native Manager/scheduler/seed/database/core port', 'automatic_service_installation': False}
        (staging / 'CAPABILITIES.json').write_text(json.dumps(capabilities, indent=2) + '\n', encoding='utf-8', newline='\n')
        output_files = [{'path': p.relative_to(staging).as_posix(), 'bytes': p.stat().st_size, 'sha256': digest(p)} for p in sorted(staging.rglob('*'), key=lambda item: item.relative_to(staging).as_posix()) if p.is_file()]
        receipt = {'schema_version': 1, 'input_contract': contract, 'output_files': output_files, 'site_configuration_or_credentials_copied': False, 'customer_operations_performed': False, 'services_installed_or_started': False}
        (staging / 'BUILD_RECEIPT.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8', newline='\n')
        if destination.exists():
            raise ValueError('Destination appeared during build; refusing replacement.')
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging)
        raise
    print('PASS: assembled ' + str(len(output_files)) + ' verified files at ' + str(destination))
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    if args.verify_only:
        verified_inputs()
        print('PASS: pinned base, immutable adapters, fail-closed patch and Windows wheelhouse')
    elif args.destination:
        build(args.destination)
    else:
        parser.error('Choose --verify-only or --destination NEW_DIRECTORY')


if __name__ == '__main__':
    main()
