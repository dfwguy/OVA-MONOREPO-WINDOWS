#!/usr/bin/env python3
"""Bundle only the clean committed tracked source tree with an integrity manifest."""
import argparse,hashlib,json,subprocess,tarfile,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();base=Path(__file__).resolve().parents[1]
subprocess.run(['python3',str(base/'tools/check_repository.py')],cwd=base,check=True)
if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=base,text=True).strip():raise SystemExit('Commit reviewed tracked source before packaging')
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=base,text=True).strip();paths=subprocess.check_output(['git','ls-files'],cwd=base,text=True).splitlines();a.output.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='ova-source-package-') as temp:
    root=Path(temp);rows=[]
    for name in paths:
        data=subprocess.check_output(['git','show',commit+':'+name],cwd=base);dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data);rows.append({'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    (root/'FILE_MANIFEST.json').write_text(json.dumps({'schema_version':1,'commit':commit,'files':rows},indent=2)+'\n')
    archive=a.output/'ova-collection-framework.tar.gz'
    with tarfile.open(archive,'w:gz') as t:
        for path in sorted(root.rglob('*')):
            if path.is_file():t.add(path,arcname=path.relative_to(root),recursive=False)
    (a.output/'SHA256SUMS.txt').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
    subprocess.run(['python3',str(base/'tools/verify_package.py'),str(root)],check=True)
print(json.dumps({'source_commit':commit,'archive':str(archive),'file_count':len(rows),'customer_data_included':False},indent=2))
