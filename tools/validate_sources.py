from pathlib import Path
import sqlite3,json,urllib.request,datetime
R=Path(__file__).resolve().parents[1];D=R/'database/bc_justice.db';O=R/'data/source-validation.json';urls=[]
if D.exists():
 c=sqlite3.connect(D)
 for t in ('catalogue_resources','catalogue_datasets'):
  try:
   cols=[x[1] for x in c.execute(f'pragma table_info({t})')]; u=next((x for x in cols if x.lower() in ('url','source_url')),None); n=next((x for x in cols if x.lower() in ('name','title')),u)
   if u:
    urls += list(c.execute(f'SELECT {n},{u} FROM {t} WHERE {u} IS NOT NULL LIMIT 500'))
  except: pass
problems=[];seen=set()
for name,url in urls:
 if not url or url in seen: continue
 seen.add(url)
 try:
  res=urllib.request.urlopen(urllib.request.Request(url,method='HEAD',headers={'User-Agent':'BCJUS/0.3.7'}),timeout=12)
  if res.geturl()!=url: problems.append({'name':name,'url':url,'message':'Redirected to '+res.geturl()})
 except Exception as e: problems.append({'name':name,'url':url,'message':str(e)})
O.parent.mkdir(exist_ok=True);O.write_text(json.dumps({'checked':len(seen),'problems':problems,'checked_at':datetime.datetime.now().isoformat()},indent=2));print('Checked',len(seen),'problems',len(problems))
