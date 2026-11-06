#!/usr/bin/env python3
"""Bounded tracked-tree publication, navigation and SVG validation."""
import ipaddress,json,re,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
base=Path(__file__).resolve().parents[1]
files=[base/x for x in subprocess.check_output(['git','ls-files'],cwd=base,text=True).splitlines()];findings=[]
for path in files:
    rel=path.relative_to(base).as_posix()
    if path.is_symlink():findings.append(rel+': symlink not allowed');continue
    if any(x in path.parts for x in ['reference','raw','state','export','lake','venv','node_modules']):findings.append(rel+': runtime/reference payload path')
    if path.suffix.lower() in ['.sqlite','.db','.parquet','.gz','.zip','.whl','.pem','.key','.env','.log','.out']:findings.append(rel+': disallowed payload extension')
    try:text=path.read_text()
    except UnicodeDecodeError:findings.append(rel+': unreviewed binary payload');continue
    patterns=[r'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----',r'glpat-[A-Za-z0-9_-]{12,}',r'(?i)\b(?:edc003|nscaletx|stn-slurm-history|job86)\b',r'(?i)(?:password|access_token|api_key)\s*[=:]\s*[\"\']([A-Za-z0-9_-]{20,})']
    # Scanning code must be able to name prohibited patterns without being mistaken for a payload.
    if rel!='tools/check_repository.py':
        for pattern in patterns:
            if re.search(pattern,text):findings.append(rel+': prohibited identifier/credential pattern')
    for address in re.findall(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])',text):
        try:
            ip=ipaddress.ip_address(address)
            if ip.is_private and not ip.is_loopback and not ip.is_unspecified:findings.append(rel+': private address literal')
        except ValueError:pass
    if path.suffix=='.md':
        for target in re.findall(r'\]\(([^)\s]+)(?:\s+"[^"]*")?\)',text):
            if ':' in target or target.startswith('#'):continue
            clean=target.split('#',1)[0]
            if clean and not (path.parent/clean).exists():findings.append(rel+': broken local link '+target)
    if path.suffix=='.svg':
        try:
            node=ET.fromstring(text)
            if node.find('{http://www.w3.org/2000/svg}title') is None:findings.append(rel+': SVG missing title')
            if re.search(r'<script|(?:href|src)=[\"\']https?://',text,re.I):findings.append(rel+': active/external SVG content')
        except ET.ParseError:findings.append(rel+': invalid SVG')
report={'status':'PASSED' if not findings else 'FAILED','tracked_files':len(files),'findings':findings,'scope':'Tracked publication tree only; bounded pattern and navigation checks, not live commissioning or exhaustive scanning'}
print(json.dumps(report,indent=2));raise SystemExit(bool(findings))
