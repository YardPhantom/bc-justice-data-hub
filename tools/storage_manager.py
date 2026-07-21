from pathlib import Path
import json,sys,shutil
R=Path(__file__).resolve().parents[1];O=R/'data/storage-report.json'
def h(n):
 for u in ['B','KB','MB','GB']:
  if n<1024:return f'{n:.1f} {u}'
  n/=1024
cats=[]
for name,rel in [('Database','database'),('Imports','imports'),('Reports','reports'),('Generated data','data')]:
 p=R/rel;fs=[x for x in p.rglob('*') if x.is_file()] if p.exists() else [];size=sum(x.stat().st_size for x in fs);cats.append({'name':name,'path':rel,'human':h(size),'files':len(fs)})
if len(sys.argv)>1 and sys.argv[1]=='cleanup':
 for p in [R/'imports/temp',R/'imports/cache']:
  if p.exists():shutil.rmtree(p)
 rs=sorted((R/'reports').glob('collection-report-*.json'),key=lambda x:x.stat().st_mtime,reverse=True) if (R/'reports').exists() else []
 for x in rs[30:]:x.unlink()
O.parent.mkdir(exist_ok=True);O.write_text(json.dumps({'categories':cats},indent=2));print('Storage report created')
