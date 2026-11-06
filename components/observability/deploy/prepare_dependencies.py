#!/usr/bin/env python3
"""Verify/extract the selected offline payload on the remote Linux management host.
No network requests. Docker load happens only with --load-images.
"""
import argparse,hashlib,json,platform,subprocess,tarfile,zipfile
from pathlib import Path

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--dependency-root',required=True,type=Path);p.add_argument('--arch',choices=['amd64','arm64']);p.add_argument('--load-images',action='store_true');a=p.parse_args()
 if platform.system()!='Linux':raise SystemExit('Run on the remote Linux host; Windows only stores/transfers these payloads.')
 arch=a.arch or {'x86_64':'amd64','aarch64':'arm64','arm64':'arm64'}.get(platform.machine())
 if not arch:raise SystemExit('Unsupported architecture: '+platform.machine())
 actual={'x86_64':'amd64','aarch64':'arm64','arm64':'arm64'}.get(platform.machine())
 if arch!=actual:raise SystemExit('Requested architecture differs from this host; do not load the wrong image/binaries.')
 root=a.dependency_root.resolve();manifest=json.loads((root/('payload-linux-'+arch+'.json')).read_text())
 for item in manifest['files']:
  path=root/item['path']
  if not path.is_file() or sha(path)!=item['sha256']:raise SystemExit('Missing or corrupt payload: '+item['path'])
 print('Offline payload hashes verified:',len(manifest['files']))
 plugin=root/('plugins-linux-'+arch);plugin.mkdir(exist_ok=True)
 with zipfile.ZipFile(root/('yesoreyeram-infinity-datasource-3.6.0.linux_'+arch+'.zip')) as z:
  for m in z.infolist():
   dest=(plugin/m.filename).resolve()
   if not dest.is_relative_to(plugin.resolve()):raise SystemExit('Unsafe plugin member')
   if m.is_dir():dest.mkdir(parents=True,exist_ok=True);continue
   dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(m));dest.chmod(0o755 if '/gpx_' in m.filename else 0o644)
 bindir=root/('node-bin-linux-'+arch);bindir.mkdir(exist_ok=True)
 for package,binary in [('node_exporter-1.8.2.linux-'+arch+'.tar.gz','node_exporter'),('cgroup_exporter-1.2.0.linux-'+arch+'.tar.gz','cgroup_exporter')]:
  with tarfile.open(root/package) as t:
   members=[m for m in t if m.isfile() and Path(m.name).name==binary]
   if len(members)!=1:raise SystemExit('Unexpected binary archive layout')
   (bindir/binary).write_bytes(t.extractfile(members[0]).read());(bindir/binary).chmod(0o755)
 with zipfile.ZipFile(root/('alloy-linux-'+arch+'.zip')) as z:
  (bindir/'alloy').write_bytes(z.read('alloy-linux-'+arch));(bindir/'alloy').chmod(0o755)
 if a.load_images:
  receipt=json.loads((root/'image-receipts.json').read_text())
  for image in receipt:
   if image['platform']!='linux/'+arch or 'archive' not in image:continue
   subprocess.run(['docker','load','--input',str(root/image['archive'])],check=True)
   actual_image=json.loads(subprocess.check_output(['docker','image','inspect',image['requested_image']],text=True))[0]
   if actual_image['Id'].removeprefix('sha256:')!=image['image_id'].removeprefix('sha256:'):raise SystemExit('Loaded image ID mismatch: '+image['requested_image'])
   if actual_image['Architecture']!=arch:raise SystemExit('Loaded image architecture mismatch')
 print('PLUGIN_DIR='+str(plugin));print('WHEELHOUSE_DIR='+str(root/('wheels-linux-'+arch)));print('NODE_BIN_DIR='+str(bindir))
 print('No systemd services installed or started. DCGM/driver compatibility still requires site acceptance.')
if __name__=='__main__':main()
