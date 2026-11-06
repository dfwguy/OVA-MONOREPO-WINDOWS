#!/usr/bin/env python3
"""Verify every recorded package member and reject unrecorded files except this manifest."""
import argparse,json,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args();root=a.directory.resolve();m=json.loads((root/'FILE_MANIFEST.json').read_text());expected=set()
for row in m['files']:
 relative=Path(row['path']);path=(root/relative).resolve()
 if relative.is_absolute() or root not in path.parents:raise SystemExit('Unsafe manifest path')
 b=path.read_bytes();expected.add(relative.as_posix())
 if len(b)!=row['bytes'] or hashlib.sha256(b).hexdigest()!=row['sha256']:raise SystemExit('Member mismatch: '+str(relative))
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='FILE_MANIFEST.json'}
if actual!=expected:raise SystemExit('Unexpected/missing members: '+str(actual^expected))
print(json.dumps({'files_verified':len(expected),'all_member_hashes_match':True}))
