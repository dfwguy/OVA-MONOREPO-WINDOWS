"""Package software-only native collection acceptance outside the repository."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path)
a = p.parse_args()
output = a.output.resolve()
if output.is_relative_to(root):
    raise SystemExit('Write the acceptance archive outside the repository.')
output.parent.mkdir(parents=True, exist_ok=True)
files = [p for p in (root / 'windows/collection').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
files += [p for p in (root / 'components/OVA_Collection_Framework/source/app').iterdir() if p.is_file()]
manifest = {'schema_version': 1, 'scope': 'Software-only isolated native collection acceptance; no private input or evidence',
            'files': [{'path': p.relative_to(root).as_posix(), 'bytes': p.stat().st_size,
                       'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(files)]}
with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for file in sorted(files):
        archive.write(file, file.relative_to(root).as_posix())
    archive.writestr('ACCEPTANCE_BUNDLE.json', json.dumps(manifest, indent=2) + '\n')
print(json.dumps({'path': str(output), 'bytes': output.stat().st_size, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}))
