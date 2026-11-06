#!/usr/bin/env python3
"""Run isolated behavior suites and produce GitLab JUnit and JSON evidence."""
import json,subprocess,sys,time,xml.etree.ElementTree as ET
from pathlib import Path
base=Path(__file__).resolve().parents[1];suite=ET.Element('testsuite',name='ova-collection');receipts=[]
commands=[['tests/test_portable.py'],['-m','unittest','discover','-s','tests','-p','test_framework.py','-v']]
for args in commands:
    start=time.monotonic();r=subprocess.run([sys.executable,*args],cwd=base,capture_output=True,text=True);elapsed=time.monotonic()-start
    name='portable-capture' if args[0].endswith('.py') else 'framework-deployment-recovery'
    case=ET.SubElement(suite,'testcase',name=name,time=f'{elapsed:.3f}')
    if r.returncode:ET.SubElement(case,'failure',message='Behavior suite failed').text=r.stdout+r.stderr
    ET.SubElement(case,'system-out').text=r.stdout+r.stderr
    receipts.append({'suite':name,'returncode':r.returncode,'elapsed_seconds':round(elapsed,3)})
    print(r.stdout);print(r.stderr,file=sys.stderr)
suite.set('tests',str(len(receipts)));suite.set('failures',str(sum(bool(x['returncode']) for x in receipts)))
ET.ElementTree(suite).write(base/'test-results.xml',encoding='utf-8',xml_declaration=True)
(base/'test-receipt.json').write_text(json.dumps({'status':'PASS' if not any(x['returncode'] for x in receipts) else 'FAIL','suites':receipts,'real_cluster_contacted':False,'real_reboot_tested':False},indent=2)+'\n')
raise SystemExit(int(any(x['returncode'] for x in receipts)))
