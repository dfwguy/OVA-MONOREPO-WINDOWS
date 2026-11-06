#!/usr/bin/env python3
"""Render docs/OVA-MONOREPO-WINDOWS-User-Guide.md to accessible HTML and a paginated PDF.

Requires markdown2 and playwright; install Chromium with `playwright install chromium`,
or set OVA_CHROMIUM_EXECUTABLE to an approved local Chromium executable.
"""
from pathlib import Path
import argparse
import os
import re
import markdown2
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CSS = r'''
@page { size:A4; margin:20mm 16mm 19mm; }
*{box-sizing:border-box}body{margin:0;color:#202a31;font:10pt/1.48 Arial,Helvetica,sans-serif}
a{color:#486f12;text-decoration:none;overflow-wrap:anywhere}p{margin:0 0 10pt}
h1{font-size:25pt;line-height:1.14;margin:0 0 18pt;color:#17242b}
h2{font-size:18pt;line-height:1.2;margin:0 0 13pt;break-after:avoid;border-bottom:2pt solid #76b900;padding-bottom:8pt}
h3{font-size:12pt;line-height:1.3;break-after:avoid;margin:17pt 0 8pt}
section.chapter{break-before:page}h1,h2,h3,h4{break-after:avoid}
table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:8.1pt;margin:12pt 0 17pt}
thead{display:table-header-group}th{background:#eaf1df;color:#253d13;text-align:left}
th,td{padding:7pt;border:1px solid #ced8c3;vertical-align:top;overflow-wrap:anywhere}tr{break-inside:avoid}
pre{background:#f0f3f4;border-left:3pt solid #76b900;padding:11pt;font-size:8pt;line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;margin:12pt 0;break-inside:avoid}
code{font-family:'DejaVu Sans Mono',monospace;font-size:.87em}p code,li code,td code{overflow-wrap:anywhere;background:#f0f3f4;padding:1pt 2pt}
ul,ol{padding-left:19pt;margin:8pt 0 12pt}li{margin:0 0 6pt}blockquote{border-left:3pt solid #76b900;padding:10pt 12pt;background:#f0f6e8;margin:13pt 0}
.cover{padding-top:20mm;break-after:page}.brand{font-size:10pt;letter-spacing:2.1pt;font-weight:bold;color:#4d7415;border-top:6pt solid #76b900;padding-top:14pt}
.cover h1{font-size:42pt;line-height:1.06;margin:28pt 0 18pt;max-width:145mm}.cover .subtitle{font-size:20pt;line-height:1.3;color:#52616a;max-width:150mm}.cover .meta{font-size:10pt;color:#65717a;border-top:1px solid #ccd6c4;padding-top:15pt;margin-top:24pt}
.cover .scope{background:#edf4e5;padding:14pt 16pt;border-left:4pt solid #76b900;margin:24pt 0;font-size:10pt}.contents{break-after:page}.contents ul{list-style:none;padding:0}.contents li{padding:7pt 0;border-bottom:1px solid #dce2d7}.contents a{font-size:11pt;color:#243b16}.lead{font-size:12pt;color:#52616a}.note{font-size:9pt;color:#647179}.diagram{margin:20pt 0;break-inside:avoid}.diagram > svg{display:block;width:100%;height:auto}svg text{font-family:Arial,Helvetica,sans-serif}
'''
DIAGRAM = '''<div class="diagram"><svg viewBox="0 0 650 238" role="img" aria-label="Windows staging and control crosses the VPN to approved Linux management backends, with collectors and jobs on scoped cluster nodes."><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#527b1b"/></marker></defs><rect x="0" y="0" width="210" height="180" rx="7" fill="#eaf2df" stroke="#76b900"/><text x="16" y="28" font-size="16" font-weight="bold">Windows VM</text><text x="16" y="55" font-size="12">Native PowerShell / SSH</text><text x="16" y="78" font-size="12">Files and payload staging</text><text x="16" y="101" font-size="12">Browser / local UI tunnels</text><text x="16" y="132" font-size="11" fill="#5c6b70">Current release: control host</text><path d="M217 78 L327 78" stroke="#527b1b" stroke-width="2" marker-end="url(#arrow)"/><text x="247" y="61" font-size="13" font-weight="bold">VPN</text><text x="218" y="103" font-size="10">BCM + app-server path</text><rect x="338" y="0" width="311" height="134" rx="7" fill="#f0f3f4" stroke="#8c9a9f"/><text x="354" y="28" font-size="16" font-weight="bold">Approved Linux management</text><text x="354" y="54" font-size="12">Application services / durable state</text><text x="354" y="78" font-size="12">BCM / Slurm / source access</text><text x="354" y="105" font-size="11" fill="#5c6b70">Current supported backend placement</text><path d="M496 141 L496 163" stroke="#527b1b" stroke-width="2" marker-end="url(#arrow)"/><rect x="338" y="174" width="311" height="63" rx="7" fill="#eaf2df" stroke="#76b900"/><text x="354" y="199" font-size="14" font-weight="bold">Scoped customer-cluster nodes</text><text x="354" y="222" font-size="12">Exporters · collectors · P2P peers · GPU jobs</text></svg></div>'''

TARGET_DIAGRAM = '''<div class="diagram"><svg viewBox="0 0 650 216" role="img" aria-label="Requested native Windows architecture: six central management tools on the Windows VM, VPN access to BCM and app-server, and only scoped collectors or workloads on customer nodes. Native backend acceptance remains pending."><defs><marker id="target-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#527b1b"/></marker></defs><rect x="0" y="0" width="295" height="215" rx="7" fill="#eaf2df" stroke="#76b900"/><text x="16" y="29" font-size="17" font-weight="bold">Windows VM · native only</text><text x="16" y="58" font-size="12">Exemplar control · P2P · PythonCM</text><text x="16" y="82" font-size="12">Auto Trigger · Observability · Collection</text><text x="16" y="114" font-size="11">Native management profiles</text><text x="16" y="140" font-size="11" fill="#7a4c16">P2P management core remains Linux</text><text x="16" y="168" font-size="11">No WSL / Hyper-V / Linux runtime</text><text x="16" y="194" font-size="11">Site commissioning remains separate</text><path d="M303 78 L407 78" stroke="#527b1b" stroke-width="2" marker-end="url(#target-arrow)"/><text x="335" y="60" font-size="13" font-weight="bold">VPN</text><rect x="419" y="0" width="230" height="115" rx="7" fill="#f0f3f4" stroke="#8c9a9f"/><text x="435" y="28" font-size="16" font-weight="bold">Customer management</text><text x="435" y="58" font-size="12">BCM head node + app-server</text><text x="435" y="86" font-size="11">Separate verified endpoint paths</text><path d="M534 122 L534 147" stroke="#527b1b" stroke-width="2" marker-end="url(#target-arrow)"/><rect x="419" y="159" width="230" height="56" rx="7" fill="#eaf2df" stroke="#76b900"/><text x="435" y="182" font-size="13" font-weight="bold">Scoped cluster nodes</text><text x="435" y="202" font-size="11">Thin collectors / peers / GPU jobs</text></svg></div>'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'docs/OVA-MONOREPO-WINDOWS-User-Guide.md')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/OVA-MONOREPO-WINDOWS-User-Guide.pdf')
    args=parser.parse_args()
    source=args.source.read_text(encoding='utf-8')
    sections=re.split(r'(?=^## )',source,flags=re.M)
    preface=sections[1] if len(sections)>1 else sections[0]
    chapters=sections[2:]
    converter=lambda s:str(markdown2.markdown(s,extras=['tables','fenced-code-blocks','header-ids']))
    toc=[]
    chapter_html=[]
    for idx,section in enumerate(chapters,1):
        title=section.splitlines()[0].removeprefix('## ')
        toc.append(f'<li><a href="#chapter-{idx}">{title}</a></li>')
        body=converter(section)
        if title.startswith('1.'):
            diagram_path=ROOT/'docs/branding/architecture.svg'
            if diagram_path.exists():
                body += '<div class="diagram">'+diagram_path.read_text()+'</div>'
        chapter_html.append(f'<section class="chapter" id="chapter-{idx}">{body}</section>')
    logo_source=(ROOT/'components/nvis-rack-status/source/static/nvidia-brand.svg').read_text().replace('width="110"','width="230"').replace('height="44"','height="43"')
    cover='''<section class="cover"><div class="brand" style="background:#0b110e;padding:16pt">'''+logo_source+'''</div><h1>OVA Monorepo<br>Windows</h1><p class="subtitle">Native Windows deployment and operator guide</p><div class="scope">Six coordinated tools · Windows preparation · VPN access<br>Service placement · Offline delivery · Acceptance and recovery</div>'''+TARGET_DIAGRAM+'''<div class="meta">Source baseline: 20261105-windows-native-02 + native profiles<br>Guide date: 6 November 2026<br>Read the deployment boundary and validation report before installation.</div></section>'''
    intro='<section class="chapter">'+converter(preface)+'</section>'
    contents='<section class="contents"><h2>Contents</h2><p class="lead">From verified source to a measured, recoverable deployment.</p><ul>'+''.join(toc)+'</ul></section>'
    html='<!doctype html><html lang="en"><head><meta charset="utf-8"><title>OVA Monorepo Windows — User Guide</title><style>'+CSS+'</style></head><body>'+cover+contents+intro+''.join(chapter_html)+'</body></html>'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    html_path=args.output.with_suffix('.html')
    html_path.write_text(html,encoding='utf-8')
    with sync_playwright() as pw:
        executable=os.environ.get('OVA_CHROMIUM_EXECUTABLE')
        options={'headless':True,'args':['--no-sandbox']}
        if executable:options['executable_path']=executable
        browser=pw.chromium.launch(**options)
        page=browser.new_page()
        page.goto(html_path.resolve().as_uri())
        page.evaluate('document.fonts.ready')
        page.emulate_media(media='print')
        page.pdf(path=str(args.output),format='A4',print_background=True,prefer_css_page_size=True,display_header_footer=True,tagged=True,outline=True,
                 header_template='<div style="font:8px Arial;color:#63715c;margin:0 60px;width:100%;border-bottom:1px solid #d9dfd1;padding-bottom:5px">OVA MONOREPO WINDOWS &nbsp; | &nbsp; DEPLOYMENT AND OPERATIONS</div>',
                 footer_template='<div style="font:8px Arial;color:#68747a;margin:0 60px;width:100%;display:flex;justify-content:space-between"><span>6 November 2026 · Check current validation report</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')
        browser.close()
    print(f'Generated {args.output.name}: {args.output.stat().st_size:,} bytes')

if __name__=='__main__':main()
