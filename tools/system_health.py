from pathlib import Path
import json, sqlite3, shutil, sys, importlib.util
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'database'/'bc_justice.db'; checks=[]
def add(name,status,detail): checks.append({'name':name,'status':status,'detail':detail})
for mod in ['openpyxl','xlrd','requests']:
    add('Python dependency: '+mod,'ok' if importlib.util.find_spec(mod) else 'warning','Installed' if importlib.util.find_spec(mod) else 'Missing; run tools\\setup.cmd')
if DB.exists():
    try:
        con=sqlite3.connect(DB); result=con.execute('PRAGMA integrity_check').fetchone()[0]; tables=con.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]; con.close(); add('SQLite database','ok' if result=='ok' else 'error',f'Integrity: {result}; {tables} tables'); db={'status':result,'size_mb':round(DB.stat().st_size/1048576,2)}
    except Exception as e: add('SQLite database','error',str(e)); db={'status':'error'}
else: add('SQLite database','warning','Database not found; run tools\\setup.cmd'); db={'status':'missing'}
for name in ['collect-new.cmd','scheduled-daily-courts.cmd','scheduled-weekly-catalogue.cmd','scheduled-monthly-statistics.cmd']:
    p=ROOT/'tools'/name; add('Script: '+name,'ok' if p.exists() else 'error','Present' if p.exists() else 'Missing')
for name in ['collection-summary.json','collection-alerts.json','data-explorer.json']:
    p=ROOT/'data'/name; add('Generated data: '+name,'ok' if p.exists() else 'warning',f'{round((datetime.now().timestamp()-p.stat().st_mtime)/3600,1)} hours old' if p.exists() else 'Missing')
disk=shutil.disk_usage(ROOT); free=round(disk.free/1073741824,2); add('Disk space','ok' if free>2 else 'warning',f'{free} GB free')
overall='error' if any(x['status']=='error' for x in checks) else ('warning' if any(x['status']=='warning' for x in checks) else 'ok')
out={'generated_at':datetime.now(timezone.utc).isoformat(),'overall':overall,'database':db,'disk':{'free_gb':free},'checks':checks}
(ROOT/'data'/'system-health.json').write_text(json.dumps(out,indent=2),encoding='utf-8'); print(f'System health: {overall}')
