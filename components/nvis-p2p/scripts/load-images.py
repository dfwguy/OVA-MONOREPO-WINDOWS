#!/usr/bin/env python3
"""Verify all minimal runtime image archives; --apply also loads/tags them offline."""
import argparse,hashlib,json,pathlib,subprocess,sys
root=pathlib.Path(__file__).resolve().parents[1]
a=argparse.ArgumentParser(description=__doc__);a.add_argument('--apply',action='store_true');a.add_argument('--engine',default='docker');args=a.parse_args();rows=json.loads((root/'offline/image-inventory.json').read_text())
for x in rows:
 h=hashlib.sha256()
 with (root/'offline'/x['archive']).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 if h.hexdigest()!=x['archive_sha256']:sys.exit('Archive checksum mismatch: '+x['name'])
print('All3 minimal runtime archive hashes verified; no MinIO/NGC credentials required.')
if args.apply:
 for x in rows:
  subprocess.run([args.engine,'load','-i',str(root/'offline'/x['archive'])],check=True,stdout=subprocess.DEVNULL)
  subprocess.run([args.engine,'image','inspect',x['config_id']],check=True,stdout=subprocess.DEVNULL)
  subprocess.run([args.engine,'tag',x['config_id'],x['local_tag']],check=True)
 print('All3 images loaded and tagged by verified configID; starts nothing.')
