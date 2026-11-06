#!/usr/bin/env python3
"""Verify actual console assets and cookie-authenticated API. Never print session tokens."""
import argparse,http.cookiejar,json,pathlib,re,ssl,urllib.request,urllib.parse
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='https://localhost:4301');p.add_argument('--ca',required=True);p.add_argument('--password-file',type=pathlib.Path);p.add_argument('--bootstrap',action='store_true');a=p.parse_args()
if not a.bootstrap and not a.password_file:p.error('Use --bootstrap only before initial password rotation; otherwise --password-file')
if urllib.parse.urlsplit(a.url).scheme!='https':p.error('Console password checks require HTTPS')
password='dragonfly' if a.bootstrap else a.password_file.read_text().rstrip('\r\n');jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=a.ca)))
with opener.open(a.url+'/',timeout=15) as f:html=f.read().decode();assert f.status==200
assets=re.findall(r'(?:src|href)="(/static/[^"]+)',html);assert assets
for asset in assets:
 with opener.open(a.url+asset,timeout=15) as f:assert f.status==200 and f.read()
# Repeated logins exercise the credential lookup, not merely an already issued bearer token.
for _ in range(3):
 req=urllib.request.Request(a.url+'/api/v1/users/signin',data=json.dumps({'name':'root','password':password}).encode(),headers={'Content-Type':'application/json'})
 with opener.open(req,timeout=15) as f:assert f.status==200 and json.load(f)['token']
 assert any(c.name=='jwt' for c in jar)
 with opener.open(a.url+'/api/v1/clusters',timeout=15) as f:assert f.status==200;json.load(f)
print(json.dumps({'result':'PASS','console_assets':len(assets),'repeated_cookie_logins':3,'authenticated_clusters':True,'session_tokens_printed':False}))
