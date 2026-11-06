#!/usr/bin/env python3
"""Verify recorded files and restore Unix permission bits after ZIP extraction."""
from pathlib import Path
import hashlib,json,os,sys
root=Path(__file__).resolve().parent
manifest=json.loads((root/'FILE_MANIFEST.json').read_text())
for row in manifest['files']:
 p=root/row['path']
 if p.is_symlink() or any(x.is_symlink() for x in p.parents):raise SystemExit('Symlink rejected: '+row['path'])
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:raise SystemExit('Integrity failure: '+row['path'])
if os.name!='posix':
 print('Payload bytes verified; restore modes after extraction on Linux.');sys.exit(0)
for row in manifest['files']:(root/row['path']).chmod(int(row['mode'],8))
print('Payload bytes verified; Unix modes restored.')
