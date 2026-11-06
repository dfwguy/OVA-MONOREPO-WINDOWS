#!/usr/bin/env python3
"""Build repository-native NVIDIA brand compositions and deterministic architecture animation.

Dependencies: playwright, Pillow. Install Chromium or set OVA_CHROMIUM_EXECUTABLE.
Edit docs/branding/architecture-status.json to reconcile final measured placements.
Existing NVIDIA logo vector paths are embedded verbatim; no logo is redrawn.
"""
from pathlib import Path
from html import escape
import io,json,hashlib,os,math,re
from PIL import Image
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/branding'
FONT='Arial,Helvetica,sans-serif'
LOGO=ROOT/'components/nvis-rack-status/source/static/nvidia-brand.svg'
EXEMPLAR=ROOT/'components/nvisova-exemplar_recipe/source/assets/nvidia-exemplar-banner.svg'
P2P=ROOT/'components/nvis-p2p/console-static/favicon/nvis-p2p.svg'

def wrap(body,w,h,title,description):
 return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="title desc"><title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>{body}</svg>\n'

def logo(x,y,w=210):
 source=LOGO.read_text()
 inner=source[source.index('>')+1:source.rindex('</svg>')]
 return f'<svg x="{x}" y="{y}" width="{w}" height="{w*179.7/974.7:.3f}" viewBox="0 0 974.7 179.7">{inner}</svg>'

def text(x,y,value,size=18,fill='#e4e9e8',weight=400,extra=''):
 return f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" fill="{fill}" {extra}>{escape(value)}</text>'

def banner():
 body='<defs><radialGradient id="halo"><stop stop-color="#76b900" stop-opacity=".17"/><stop offset="1" stop-color="#76b900" stop-opacity="0"/></radialGradient><linearGradient id="bg" x2="1" y2="1"><stop stop-color="#080d0c"/><stop offset="1" stop-color="#17201c"/></linearGradient><pattern id="grid" width="30" height="30" patternUnits="userSpaceOnUse"><path d="M30 0H0V30" fill="none" stroke="#a3c88a" stroke-opacity=".06"/></pattern></defs>'
 body+='<rect width="1600" height="450" rx="22" fill="url(#bg)"/><rect width="1600" height="450" rx="22" fill="url(#grid)"/><rect width="9" height="450" fill="#76b900"/><circle cx="1330" cy="180" r="330" fill="url(#halo)"/>'
 body+=logo(55,40,220)
 body+=text(56,155,'OVA MONOREPO',68,'#fff',750,extra='letter-spacing="-1.8"')
 body+=text(56,231,'WINDOWS',68,'#fff',750,extra='letter-spacing="-1.8"')
 body+=text(59,282,'Six coordinated tools. One operational workspace.',23,'#c1d0c4')
 chips=[('NATIVE WINDOWS',196),('SIX TOOLS',127),('MEASURED EVIDENCE',214)]
 x=59
 for label,w in chips:
  body+=f'<rect x="{x}" y="324" width="{w}" height="36" rx="18" fill="#76b900" fill-opacity=".09" stroke="#638f2c"/>'
  body+=text(x+17,347,label,12,'#b8dc85',700,extra='letter-spacing="1"')
  x+=w+12
 body+=text(59,406,'PREPARE  /  CONNECT  /  OBSERVE  /  VALIDATE  /  RECOVER',14,'#8ea291',500,extra='letter-spacing="1.8"')
 # Six component nodes form a coordinated system, not a new corporate logo.
 cx,cy=1321,213
 for i,label in enumerate(['RACK','P2P','OBSERVE','COLLECT','TRIGGER','EXEMPLAR']):
  a=-math.pi/2+i*math.pi/3;x=cx+145*math.cos(a);y=cy+145*math.sin(a)
  body+=f'<path d="M{cx} {cy} L{x:.2f} {y:.2f}" stroke="#76b900" stroke-opacity=".45" stroke-width="2"/>'
  body+=f'<rect x="{x-65:.2f}" y="{y-25:.2f}" width="130" height="50" rx="12" fill="#121e16" stroke="#759b46"/>'
  body+=text(x,y+5,label,12,'#d9eac9',700,extra='text-anchor="middle" letter-spacing="1.1"')
 body+=f'<circle cx="{cx}" cy="{cy}" r="65" fill="#76b900" fill-opacity=".12" stroke="#76b900" stroke-width="2"/>'
 body+=text(cx,cy+7,'OVA',28,'#fff',700,extra='text-anchor="middle"')
 return wrap(body,1600,450,'NVIDIA OVA Monorepo Windows','NVIDIA brand composition derived from the Exemplar green and black banner, using the existing NVIDIA vector logo unchanged. Six tools surround one operational workspace. No deployment acceptance claim.')

def mark():
 body='<rect width="1020" height="160" rx="14" fill="#0b110e"/><rect width="7" height="160" fill="#76b900"/>'
 body+=logo(34,59,225)+'<path d="M296 36V124" stroke="#3b4f3a"/>'
 body+=text(329,76,'OVA MONOREPO',34,'#fff',700)+text(331,112,'WINDOWS  /  SIX-TOOL MANAGEMENT',16,'#9db48f',500,extra='letter-spacing="1.4"')
 return wrap(body,1020,160,'NVIDIA OVA Monorepo Windows mark','Unmodified existing NVIDIA eye and wordmark beside the OVA Monorepo Windows project title.')

def avatar():
 body='<rect width="512" height="512" rx="54" fill="#0b110e"/><rect x="0" y="54" width="8" height="404" fill="#76b900"/><path d="M56 189H456" stroke="#3a5234"/>'
 body+=logo(80,76,352)
 body+=text(256,332,'OVA',136,'#fff',750,extra='text-anchor="middle" letter-spacing="-4"')
 body+=text(256,398,'WINDOWS',27,'#a7cd7d',600,extra='text-anchor="middle" letter-spacing="6"')
 body+='<path d="M189 444H323" stroke="#76b900" stroke-width="4"/>'
 return wrap(body,512,512,'NVIDIA OVA Windows avatar','NVIDIA eye and wordmark vector unchanged, composed with the OVA Windows project title.')

def architecture(status):
 body='<defs><linearGradient id="back" x2="1" y2="1"><stop stop-color="#0a100e"/><stop offset="1" stop-color="#131d17"/></linearGradient><marker id="arrow" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto"><path d="M0 0L9 4.5L0 9" fill="#76b900"/></marker></defs><rect width="1600" height="1000" rx="24" fill="url(#back)"/>'
 body+=logo(46,33,185)+text(1550,62,'OVA  /  WINDOWS',17,'#a4bd95',600,extra='text-anchor="end" letter-spacing="2"')
 body+=text(46,140,status['title'],39,'#fff',700)+text(47,181,status['subtitle'],19,'#a9bdad')
 body+='<rect x="44" y="227" width="908" height="594" rx="20" fill="#142018" stroke="#476638"/><rect x="44" y="227" width="908" height="65" rx="20" fill="#20341b"/>'
 body+=text(69,268,'NVIDIA / ITSS WINDOWS VM',22,'#eef7e8',700)+text(929,267,'NO LINUX VIRTUALIZATION',12,'#b9d49b',600,extra='text-anchor="end" letter-spacing="1"')
 for idx,tool in enumerate(status['tools']):
  x=68+(idx%2)*438;y=316+(idx//2)*158
  tone=tool.get('tone','pending');color={'pending':'#e2bb64','boundary':'#a9c1d5','verified':'#a7d76e'}.get(tone,'#e2bb64')
  body+=f'<rect x="{x}" y="{y}" width="414" height="137" rx="12" fill="#101a14" stroke="#314e32"/>'
  body+=f'<rect x="{x}" y="{y+17}" width="3" height="31" fill="{color}"/>'
  body+=text(x+20,y+36,tool['name'],22,'#f4f7f2',700)+text(x+20,y+67,tool['line'],16,'#b3c3b5')
  body+=f'<circle cx="{x+25}" cy="{y+104}" r="4" fill="{color}"/>'+text(x+39,y+109,tool['status'],14,color,500)
 # Control flow across VPN. Motion represents flow only, never a passing test.
 body+='<path id="vpn-flow" d="M965 476H1112" fill="none" stroke="#76b900" stroke-width="3" marker-end="url(#arrow)"/>'
 body+=text(1039,438,'VPN',23,'#d4e8c5',700,extra='text-anchor="middle"')+text(1039,515,'Trusted control',13,'#9eb594',400,extra='text-anchor="middle"')
 body+='<rect x="1131" y="287" width="424" height="292" rx="18" fill="#121c19" stroke="#526663"/>'
 body+=text(1156,329,'CUSTOMER MANAGEMENT',20,'#f1f6ef',700)+text(1156,374,'BCM head node',24,'#d9e6d6',600)+text(1156,414,'App-server',24,'#d9e6d6',600)
 body+=text(1156,457,'Distinct identity + endpoint checks',16,'#a7bcb3')+text(1156,499,'P2P management core: Linux',17,'#e2bb64',600)+text(1156,536,'Current placement exception to resolve',14,'#b2c4b8')
 body+='<path id="cluster-flow" d="M1343 592V645" fill="none" stroke="#76b900" stroke-width="3" marker-end="url(#arrow)"/><rect x="1131" y="665" width="424" height="157" rx="18" fill="#14221a" stroke="#476638"/>'
 body+=text(1156,706,'SCOPED CLUSTER NODES',20,'#f1f6ef',700)+text(1156,746,'Thin collectors / exporters / peers',17,'#b7cbb7')+text(1156,782,'GPU workloads stay on cluster',17,'#b7cbb7')
 body+='<circle id="vpn-packet" cx="975" cy="476" r="6" fill="#d2ff9e"/><circle id="cluster-packet" cx="1343" cy="602" r="5" fill="#d2ff9e"/>'
 body+='<path d="M46 867H1554" stroke="#334935"/>'
 body+=text(47,909,'NATIVE PROCESS  ≠  LIVE CLUSTER ACCEPTANCE',17,'#c5d7bf',700,extra='letter-spacing="1.4"')+text(47,950,status['footer'],16,'#8ea78f')
 return wrap(body,1600,1000,'NVIDIA OVA six-tool architecture',status['subtitle']+'. '+status['footer'])

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 state=json.loads((OUT/'architecture-status.json').read_text())
 for filename,content in [('ova-monorepo-banner.svg',banner()),('ova-monorepo-mark.svg',mark()),('architecture.svg',architecture(state)),('ova-monorepo-avatar.svg',avatar())]:
  (OUT/filename).write_text(content)
 frames=[]
 with sync_playwright() as pw:
  options={'headless':True,'args':['--no-sandbox']}
  executable=os.environ.get('OVA_CHROMIUM_EXECUTABLE')
  if executable:options['executable_path']=executable
  browser=pw.chromium.launch(**options)
  page=browser.new_page(viewport={'width':1200,'height':750},device_scale_factor=1)
  page.set_content('<html><body style="margin:0;background:#0a100e">'+architecture(state).replace('width="1600" height="1000"','width="1200" height="750"',1)+'</body></html>')
  page.evaluate('document.fonts.ready')
  for idx in range(40):
   t=idx/40
   page.evaluate('''t=>{const p=document.getElementById('vpn-packet');p.setAttribute('cx',975+125*t);const q=document.getElementById('cluster-packet');q.setAttribute('cy',600+37*((t+.35)%1));}''',t)
   png=page.screenshot()
   frames.append(Image.open(io.BytesIO(png)).convert('RGB'))
  page.screenshot(path=str(OUT/'architecture-preview.png'))
  # A common deterministic palette prevents flicker across frames.
  palette=frames[0].quantize(colors=192,method=Image.Quantize.MEDIANCUT)
  quantized=[frame.quantize(palette=palette,dither=Image.Dither.NONE) for frame in frames]
  quantized[0].save(OUT/'architecture.gif',save_all=True,append_images=quantized[1:],duration=120,loop=0,optimize=False,disposal=2)
  page.set_viewport_size({'width':1200,'height':338})
  page.set_content('<html><body style="margin:0">'+banner().replace('width="1600" height="450"','width="1200" height="338"',1)+'</body></html>')
  page.screenshot(path=str(OUT/'banner-preview.png'))
  page.set_viewport_size({'width':512,'height':512})
  page.set_content('<html><body style="margin:0">'+avatar()+'</body></html>')
  page.screenshot(path=str(OUT/'ova-monorepo-avatar.png'))
  browser.close()
 sources=[{'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in [LOGO,EXEMPLAR,P2P]]
 provenance={'generator':'tools/render_branding.py','logo_policy':'NVIDIA eye and wordmark SVG paths reused verbatim from existing Rack Status asset; no AI generation or redraw.','style_reference':'Current Exemplar green #76B900 and black banner; current NVIS P2P console mark as source reference, not an invented root README.','requested_reference_repositories':['https://gitlab-master.nvidia.com/nvis-ova/nvisova-exemplar_recipe','https://gitlab-master.nvidia.com/nvis-ova/nvis-p2p'],'sources':sources,'status_source':'docs/branding/architecture-status.json','animation':{'frames':40,'duration_ms_per_frame':120,'loop':True,'motion_meaning':'Control/data flow illustration only; does not signify successful validation.'},'outputs':[]}
 for name in ['ova-monorepo-banner.svg','ova-monorepo-mark.svg','architecture.svg','architecture.gif','ova-monorepo-avatar.svg','ova-monorepo-avatar.png']:
  p=OUT/name;provenance['outputs'].append({'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 (OUT/'ASSET_PROVENANCE.json').write_text(json.dumps(provenance,indent=2)+'\n')
 print(json.dumps(provenance['outputs']))

if __name__=='__main__':main()
