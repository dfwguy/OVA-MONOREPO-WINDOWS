#!/usr/bin/env python3
"""Build/verify the offline Windows distribution with a complete embedded file manifest."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
import zlib

MANIFEST_NAME = 'RELEASE_MANIFEST.json'
MAX_MEMBER_BYTES = 2_000_000_000
FIXED_DATE = (2026, 11, 6, 0, 0, 0)
EXCLUDED_DIRS = {'.git', 'node_modules', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.tox', '.nox', '.cache', '.venv', 'venv', 'env', 'htmlcov', '.nyc_output', 'playwright-report', 'test-results', 'tests-output', 'test-output'}
PRIVATE_DIRS = {'.ssh', '.gnupg', 'secrets', 'private', 'quarantine', 'credentials', 'site-private', 'site-data'}
PRIVATE_NAMES = {'.env', '.git-credentials', 'id_rsa', 'id_ed25519', 'id_ecdsa', '.rack_web_secret_key', 'gitlab_token', 'slack_bot_token', 'slack_app_token', 'password.txt', 'credentials.json', 'secrets.json'}
STORED_SUFFIXES = {'.zip', '.whl', '.gz', '.bz2', '.xz', '.7z', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.pdf', '.exe', '.dll', '.woff', '.woff2', '.mp4', '.mp3'}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def validate_path(name, prefixes=None):
    rel = PurePosixPath(name)
    if rel.as_posix() != name or any(part in {'', '.', '..'} for part in name.split('/')):
        raise ValueError('Release path normalization is forbidden: ' + name)
    if not rel.parts or rel.is_absolute() or '..' in rel.parts or '\\' in name or ':' in name or '\x00' in name:
        raise ValueError('Unsafe/nonportable release path: ' + name)
    for part in rel.parts:
        if part in {'.', '..'} or part.endswith(('.', ' ')) or any(ord(c) < 32 or c in '<>"|?*' for c in part) or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I):
            raise ValueError('Nonportable Windows path component: ' + name)
    if prefixes is not None:
        for length in range(1, len(rel.parts) + 1):
            prefix = '/'.join(rel.parts[:length])
            folded = prefix.casefold()
            if folded in prefixes and prefixes[folded] != prefix:
                raise ValueError('Windows case-colliding release path: ' + name)
            prefixes[folded] = prefix
    return rel


def excluded(name, directory=False):
    parts = PurePosixPath(name).parts
    if parts and parts[0] == 'artifacts':
        return True
    if any(part.lower() in EXCLUDED_DIRS or part.lower().endswith('-venv') for part in parts):
        return True
    leaf = parts[-1] if parts else ''
    if leaf in {'.coverage', '.DS_Store'} or leaf.endswith(('.pyc', '.pyo')):
        return True
    return name == MANIFEST_NAME


def require_public_path(name):
    parts = PurePosixPath(name).parts
    if any(part.lower() in PRIVATE_DIRS for part in parts) or parts[-1].lower() in PRIVATE_NAMES or parts[-1].lower().endswith(('.pfx', '.p12', '.kdbx', '.key')):
        raise ValueError('Private/runtime credential path is forbidden in the release: ' + name)
    lower = name.lower()
    if '/var/logs/' in '/' + lower and parts[-1] != '.gitkeep':
        raise ValueError('Generated runtime log is forbidden: ' + name)
    if any(segment in '/' + lower for segment in ['/var/cache/', '/var/state/']):
        raise ValueError('Generated runtime state/cache is forbidden: ' + name)


def read_constraints(root):
    constraints = {}
    manifests = [root / 'control/FILE_MANIFEST.json', *sorted((root / 'components').glob('*/FILE_MANIFEST.json'))]
    for manifest in manifests:
        if not manifest.is_file():
            continue
        data = json.loads(manifest.read_text(encoding='utf-8'))
        for entry in data['files']:
            relative = (manifest.parent.relative_to(root) / entry['path']).as_posix()
            validate_path(relative)
            if relative in constraints and constraints[relative]['sha256'] != entry['sha256']:
                raise ValueError('Conflicting component manifest entries: ' + relative)
            constraints[relative] = entry
    return constraints


def inspect_source(root, strict_layout=True):
    root = root.resolve()
    if strict_layout:
        for name in ['README.md', 'control/FILE_MANIFEST.json', 'components', 'windows', 'docs', 'evidence']:
            if not (root / name).exists():
                raise ValueError('Wrong or incomplete repository root; missing ' + name)
    constraints = read_constraints(root)
    records, prefixes, skipped = [], {}, []
    for current, directories, files in os.walk(root, followlinks=False):
        parent = Path(current)
        kept = []
        for name in sorted(directories):
            path = parent / name
            relative = path.relative_to(root).as_posix()
            if excluded(relative, True):
                skipped.append(relative + '/')
                continue
            if path.is_symlink():
                raise ValueError('Directory symlinks are forbidden: ' + relative)
            kept.append(name)
        directories[:] = kept
        for name in sorted(files):
            path = parent / name
            relative = path.relative_to(root).as_posix()
            if excluded(relative):
                skipped.append(relative)
                continue
            validate_path(relative, prefixes)
            require_public_path(relative)
            origin = None
            source = path
            if path.is_symlink():
                link_text = os.readlink(path)
                if Path(link_text).is_absolute():
                    raise ValueError('Absolute file symlink is forbidden: ' + relative)
                try:
                    source = path.resolve(strict=True)
                except (OSError, RuntimeError) as error:
                    raise ValueError('Broken/looping source symlink: ' + relative) from error
                if not source.is_relative_to(root) or not source.is_file():
                    raise ValueError('External or non-file symlink is forbidden: ' + relative)
                target = source.relative_to(root).as_posix()
                validate_path(target)
                require_public_path(target)
                if excluded(target):
                    raise ValueError('Symlink target is excluded/private: ' + relative)
                origin = {'source_kind': 'internal-file-symlink-materialized', 'source_symlink_target': link_text, 'resolved_target': target, 'archive_kind': 'regular-file'}
            status = source.stat()
            if not stat.S_ISREG(status.st_mode):
                raise ValueError('Only regular source files are supported: ' + relative)
            if status.st_size >= MAX_MEMBER_BYTES:
                raise ValueError('Member must be below2GB for Windows Expand-Archive: ' + relative)
            expected = constraints.get(relative)
            if expected and expected.get('mode') is not None:
                mode = int(str(expected['mode']), 8) & 0o777
                mode_basis = 'component-file-manifest'
            elif os.name == 'posix':
                mode = stat.S_IMODE(status.st_mode) & 0o777
                mode_basis = 'packaging-posix-filesystem'
            else:
                mode, mode_basis = 0o644, 'normalized-regular-file; source-specific modes remain in component manifests'
            row = {'path': relative, 'bytes': status.st_size, 'sha256': digest(source), 'mode': f'{mode:04o}', 'mode_basis': mode_basis}
            if origin:
                row.update(origin)
            if expected and (row['sha256'] != expected['sha256'] or row['bytes'] != expected['bytes']):
                raise ValueError('Component integrity mismatch: ' + relative)
            records.append({'row': row, 'path': path, 'source': source, 'signature': (status.st_size, status.st_mtime_ns, status.st_ino), 'link': os.readlink(path) if path.is_symlink() else None})
    records.sort(key=lambda item: item['row']['path'])
    actual = {item['row']['path'] for item in records}
    missing = set(constraints) - actual
    if missing:
        raise ValueError('Component manifest would reference excluded/missing files: ' + ', '.join(sorted(missing)[:5]))
    if len(records) > 100000:
        raise ValueError('Unexpected release member count')
    return root, records, sorted(skipped)


def source_identities(root, records):
    identities = []
    for record in records:
        relative = record['row']['path']
        if Path(relative).name in {'PROVENANCE.json', 'RELEASE_INDEX.json', 'RELEASE_INVENTORY.json', 'DEPENDENCIES.json', 'BUILD_CONTRACT.json', 'ADAPTER_REVISION.json'}:
            identities.append({'path': relative, 'sha256': record['row']['sha256']})
    head, dirty = None, None
    if (root / '.git').exists() and shutil.which('git'):
        result = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True, capture_output=True)
        if result.returncode == 0:
            head = result.stdout.strip()
            status = subprocess.run(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=normal', '--', '.', ':(exclude)artifacts'], text=True, capture_output=True)
            dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    return {'git_head_before_artifact': head, 'source_changes_present': dirty, 'file_manifest_is_authoritative': True, 'identity_files': identities}


def manifest_for(root, records, skipped, release_id):
    return {'schema_version': 1, 'release_id': release_id, 'distribution': 'Primary native Windows offline source/dependency distribution with preserved original tool references', 'manifest_self_exemption': [MANIFEST_NAME], 'file_count': len(records), 'total_payload_bytes': sum(r['row']['bytes'] for r in records), 'max_member_bytes_exclusive': MAX_MEMBER_BYTES, 'fixed_zip_timestamp': list(FIXED_DATE), 'zip_metadata': {'creator_system': 'Unix metadata; regular files only; internal file symlinks materialized', 'deflate_level': 1, 'zlib_version': zlib.ZLIB_VERSION, 'reproducibility_scope': 'Sorted paths, fixed timestamp and normalized attrs. Byte-for-byte reproduction requires the same source/mode inputs and zlib implementation/version.'}, 'source_identities': source_identities(root, records), 'exclusions': {'top_level_artifacts': 'Excluded: previous duplicate control ZIP and external legacy Linux Observability dependency packs; these remain separately available in GitLab LFS and the original dependency index.', 'native_dependency_closure': 'Included under windows/: native profile executables, wheels, runtime prerequisites and source adapters. This does not qualify every legacy Linux/GPU workload dependency or all production features.', 'cache_directory_names': sorted(EXCLUDED_DIRS), 'excluded_paths': skipped}, 'files': [r['row'] for r in records]}


def summary(root, records, skipped):
    return {'source_root': str(root), 'included_files': len(records), 'payload_bytes': sum(r['row']['bytes'] for r in records), 'largest_member_bytes': max((r['row']['bytes'] for r in records), default=0), 'max_relative_path_characters': max((len(r['row']['path']) for r in records), default=0), 'materialized_internal_file_symlinks': [r['row']['path'] for r in records if r['link'] is not None], 'excluded_paths': len(skipped)}


def build(root, output, release_id='OVA-MONOREPO-WINDOWS-native-20261106', strict_layout=True):
    root, records, skipped = inspect_source(root, strict_layout)
    output = output.resolve()
    if output.exists():
        raise ValueError('Preserve the existing artifact; choose a new output path.')
    if output.is_relative_to(root) and not output.is_relative_to(root / 'artifacts'):
        raise ValueError('Output must be outside the checkout or under top-level artifacts/.')
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = manifest_for(root, records, skipped, release_id)
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode('utf-8')
    fd, temporary = tempfile.mkstemp(prefix=output.name + '.', suffix='.partial', dir=output.parent)
    os.close(fd)
    temporary = Path(temporary)
    try:
        with zipfile.ZipFile(temporary, 'w', allowZip64=True, compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            members = [(record['row']['path'], record) for record in records] + [(MANIFEST_NAME, None)]
            for relative, record in sorted(members):
                info = zipfile.ZipInfo(relative, FIXED_DATE)
                info.create_system = 3
                mode = int(record['row']['mode'], 8) if record else 0o644
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.compress_type = zipfile.ZIP_STORED if Path(relative).suffix.lower() in STORED_SUFFIXES else zipfile.ZIP_DEFLATED
                info._compresslevel = 1
                with archive.open(info, 'w') as target:
                    if record is None:
                        target.write(manifest_bytes)
                        continue
                    h, count = hashlib.sha256(), 0
                    with record['source'].open('rb') as stream:
                        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                            target.write(chunk)
                            h.update(chunk)
                            count += len(chunk)
                    if h.hexdigest() != record['row']['sha256'] or count != record['row']['bytes']:
                        raise ValueError('Source changed while archiving: ' + relative)
        for record in records:
            status = record['source'].stat()
            if (status.st_size, status.st_mtime_ns, status.st_ino) != record['signature'] or (os.readlink(record['path']) if record['path'].is_symlink() else None) != record['link']:
                raise ValueError('Source changed during build: ' + record['row']['path'])
        live = set()
        for current, directories, files in os.walk(root, followlinks=False):
            parent = Path(current)
            directories[:] = [name for name in directories if not excluded((parent / name).relative_to(root).as_posix(), True)]
            for name in files:
                relative = (parent / name).relative_to(root).as_posix()
                if not excluded(relative):
                    live.add(relative)
        if live != {record['row']['path'] for record in records}:
            raise ValueError('Source membership changed during build.')
        if output.exists():
            raise ValueError('Output appeared during build; refusing replacement.')
        temporary.rename(output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    provenance = {'release_id': release_id, 'artifact': output.name, 'bytes': output.stat().st_size, 'sha256': digest(output), 'embedded_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(), 'payload_files': len(records), 'source_identities': manifest['source_identities'], 'built_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'publication_performed': False}
    output.with_name(output.name + '.SHA256SUMS').write_text(provenance['sha256'] + '  ' + output.name + '\n', encoding='utf-8', newline='\n')
    output.with_name(output.name + '.PROVENANCE.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8', newline='\n')
    return provenance


def verify(archive_path, expected_sha256=None):
    if expected_sha256 and digest(archive_path) != expected_sha256.lower():
        raise ValueError('External archive SHA-256 mismatch')
    with zipfile.ZipFile(archive_path) as archive:
        infos, prefixes = {}, {}
        for info in archive.infolist():
            if info.orig_filename != info.filename:
                raise ValueError('ZIP member filename normalization is forbidden')
            validate_path(info.orig_filename, prefixes)
            require_public_path(info.filename)
            if info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError('Encrypted/unsupported archive compression is forbidden')
            if info.filename in infos or info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Duplicate/directory/symlink archive member')
            if info.file_size >= MAX_MEMBER_BYTES:
                raise ValueError('Oversized Windows archive member')
            infos[info.filename] = info
        manifest = json.loads(archive.read(MANIFEST_NAME))
        rows = manifest['files']
        if manifest['file_count'] != len(rows) or manifest['total_payload_bytes'] != sum(row['bytes'] for row in rows):
            raise ValueError('Embedded manifest totals mismatch')
        if len({row['path'] for row in rows}) != len(rows) or set(infos) != {row['path'] for row in rows} | {MANIFEST_NAME}:
            raise ValueError('Archive manifest membership mismatch')
        for row in rows:
            info = infos[row['path']]
            h, count = hashlib.sha256(), 0
            with archive.open(info) as stream:
                for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                    h.update(chunk)
                    count += len(chunk)
            if count != row['bytes'] or h.hexdigest() != row['sha256']:
                raise ValueError('Archive payload integrity mismatch: ' + row['path'])
            if info.date_time != FIXED_DATE or (info.external_attr >> 16 & 0o777) != int(row['mode'], 8):
                raise ValueError('Archive metadata mismatch: ' + row['path'])
    return {'status': 'PASS', 'release_id': manifest['release_id'], 'verified_payload_files': len(rows), 'manifest_self_exemption': [MANIFEST_NAME]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ['plan', 'build']:
        command = sub.add_parser(action)
        command.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
        if action == 'build':
            command.add_argument('--output', required=True, type=Path)
            command.add_argument('--release-id', default='OVA-MONOREPO-WINDOWS-native-20261106')
    command = sub.add_parser('verify')
    command.add_argument('archive', type=Path)
    command.add_argument('--expected-sha256')
    args = parser.parse_args()
    if args.action == 'plan':
        root, records, skipped = inspect_source(args.root)
        result = summary(root, records, skipped)
    elif args.action == 'build':
        result = build(args.root, args.output, args.release_id)
    else:
        result = verify(args.archive, args.expected_sha256)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
        sys.exit(1)
