#!/usr/bin/env python3
from __future__ import annotations
import json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'database'/'bc_justice.db'; DATA=ROOT/'data'; REPORTS=ROOT/'reports'
def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def main():
 run_status=sys.argv[1] if len(sys.argv)>1 else 'unknown'; REPORTS.mkdir(exist_ok=True); alerts=[]; failures=[]; changed=[]; stale=[]; missing=[]
 if DB.exists():
  c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if 'catalogue_resources' in names:
   failures += [dict(r) for r in c.execute("SELECT name,import_error AS error,local_path FROM catalogue_resources WHERE import_state='failed' ORDER BY imported_at DESC LIMIT 50")]
   missing += [dict(r) for r in c.execute("SELECT name,url FROM catalogue_resources WHERE collection_state='enabled' AND (local_path IS NULL OR local_path='') LIMIT 50")]
  if 'statcan_sources' in names:
   failures += [dict(r) for r in c.execute("SELECT title AS name,error,source_url AS local_path FROM statcan_sources WHERE status='failed'")]
   changed += [dict(r) for r in c.execute("SELECT title AS name,last_changed,source_url FROM statcan_sources WHERE last_changed >= datetime('now','-2 days')")]
   stale += [dict(r) for r in c.execute("SELECT title AS name,latest_year,source_url FROM statcan_sources WHERE latest_year IS NULL OR latest_year < CAST(strftime('%Y','now') AS INTEGER)-2")]
 for f in failures: alerts.append({'severity':'error','type':'failed-import','title':f.get('name'),'detail':f.get('error'),'source':f.get('local_path')})
 for m in missing: alerts.append({'severity':'warning','type':'missing-source','title':m.get('name'),'detail':'Enabled resource has not been downloaded.','source':m.get('url')})
 for s in stale: alerts.append({'severity':'warning','type':'stale-dataset','title':s.get('name'),'detail':f"Latest data year: {s.get('latest_year') or 'unknown'}",'source':s.get('source_url')})
 for x in changed: alerts.append({'severity':'info','type':'changed-source','title':x.get('name'),'detail':f"Source changed: {x.get('last_changed')}",'source':x.get('source_url')})
 payload={'generatedAt':now(),'runStatus':run_status,'summary':{'alerts':len(alerts),'failed':len(failures),'missing':len(missing),'changed':len(changed),'stale':len(stale)},'alerts':alerts}
 (DATA/'collection-alerts.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8')
 lines=[f"BC Justice Data Hub collection report",f"Generated: {payload['generatedAt']}",f"Run status: {run_status}",f"Failed: {len(failures)} | Missing: {len(missing)} | Changed: {len(changed)} | Stale: {len(stale)}",'']
 lines += [f"[{a['severity'].upper()}] {a['type']}: {a['title']} — {a['detail']}" for a in alerts] or ['No collection alerts.']
 (REPORTS/'collection-run-latest.txt').write_text('\n'.join(lines),encoding='utf-8')
 (REPORTS/f"collection-run-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt").write_text('\n'.join(lines),encoding='utf-8')
 print(lines[3]); return 0
if __name__=='__main__': raise SystemExit(main())
