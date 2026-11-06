"""Report freshness and errors; failure exit is suitable for an external monitoring check."""
import json,sys,datetime
from pathlib import Path
from history import ROOT
from settings import CONFIG
now=datetime.datetime.now(datetime.timezone.utc);out={};bad=[]
for kind,name in [('metadata','metadata-health.json'),('live','live-health.json'),('publication','health.json'),('search','search-health.json')]:
    try:
        x=json.loads((ROOT/'state'/name).read_text());age=(now-datetime.datetime.fromisoformat(x['updated_utc'])).total_seconds();budget=CONFIG.get('freshness_budget_seconds',{}).get(kind,600)
        out[kind]={'age_seconds':age,'budget_seconds':budget,'fresh':age<=budget}
        if age>budget:bad.append(kind+' stale')
        if kind=='publication':
            out['open_errors']=x.get('open_error_count');out['disk_warning']=x.get('disk_warning');out['coverage']=x.get('coverage_by_type')
            if x.get('open_error_count'):bad.append('collection errors open')
            if x.get('disk_warning'):bad.append('disk low')
    except Exception as e:out[kind]={'error':str(e)};bad.append(kind+' unavailable')
if CONFIG.get('remote_capture_enabled',False):
    import sqlite3
    try:
        with sqlite3.connect('file:'+str(ROOT/'state/index.sqlite')+'?mode=ro',uri=True) as journal:
            incomplete=journal.execute("select count(*) from remote_coverage where status in ('partial','error')").fetchone()[0]
        out['remote_incomplete_host_records']=incomplete
        if incomplete:bad.append('remote host coverage incomplete')
    except Exception:bad.append('remote coverage unavailable')
print(json.dumps({'checked_utc':now.isoformat(),'checks':out,'problems':bad},indent=2));sys.exit(bool(bad))
