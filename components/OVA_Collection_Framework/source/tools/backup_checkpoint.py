#!/usr/bin/env python3
"""Online SQLite checkpoint backup. Payload/file backup remains a separate required step."""
import argparse,sqlite3,json,hashlib,datetime
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();cfg=json.loads(a.config.read_text());root=Path(cfg['root'])
if a.output.exists():raise SystemExit('Choose a new backup filename; never overwrite a prior checkpoint backup')
source=sqlite3.connect('file:'+str(root/'state/index.sqlite')+'?mode=ro',uri=True,timeout=60);dest=sqlite3.connect(a.output)
try:
 source.backup(dest,pages=256,sleep=0.1)
 check=dest.execute('pragma integrity_check').fetchone()[0]
 if check!='ok':raise RuntimeError(check)
finally:dest.close();source.close()
print(json.dumps({'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checkpoint_backup':str(a.output),'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest(),'integrity_check':'ok','payload_backup_required':True},indent=2))
