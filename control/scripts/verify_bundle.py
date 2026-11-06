#!/usr/bin/env python3
"""Verify a transferred IREN release against its FILE_MANIFEST.json. No dependencies."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

def verify(root):
    root = root.resolve()
    manifest = json.loads((root / 'FILE_MANIFEST.json').read_text(encoding='utf-8'))
    errors = []
    listed = set()
    for entry in manifest['files']:
        rel = PurePosixPath(entry['path'])
        if not rel.parts or rel.is_absolute() or '..' in rel.parts or '\\' in entry['path'] or ':' in entry['path']:
            errors.append(f"Unsafe manifest path: {entry['path']}")
            continue
        if entry['path'] in listed:
            errors.append(f"Duplicate manifest path: {entry['path']}")
        listed.add(entry['path'])
        path = root.joinpath(*rel.parts)
        if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file():
            errors.append(f"Missing/unsafe file: {entry['path']}")
            continue
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                h.update(chunk)
        if path.stat().st_size != entry['bytes'] or h.hexdigest() != entry['sha256']:
            errors.append(f"Integrity mismatch: {entry['path']}")
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    for extra in sorted(actual - listed - {'FILE_MANIFEST.json'}):
        errors.append(f'Unlisted file: {extra}')
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f"PASS: {len(manifest['files'])} payload files match SHA-256 and byte count.")
    print('Integrity is relative to this manifest; compare the release ZIP checksum with the NVFTP handoff receipt.')
    return 0

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path, nargs='?', default=Path(__file__).resolve().parents[1])
    sys.exit(verify(p.parse_args().root))
