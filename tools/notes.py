from pathlib import Path
import sqlite3,csv,json,sys,uuid,datetime
R=Path(__file__).resolve().parents[1]; D=R/'database/bc_justice.db'; O=R/'data/private-notes.json'
c=sqlite3.connect(D); c.execute('CREATE TABLE IF NOT EXISTS private_notes(note_id TEXT PRIMARY KEY,title TEXT,entity_ref TEXT,note_text TEXT,created_at TEXT,updated_at TEXT)')
if len(sys.argv)>1 and sys.argv[1]=='apply':
 p=Path(sys.argv[2] if len(sys.argv)>2 else Path(__file__).with_name('note-actions.csv')); p=p if p.is_absolute() else (Path.cwd()/p if (Path.cwd()/p).exists() else Path(__file__).parent/p.name)
 for x in csv.DictReader(p.open(encoding='utf-8-sig',newline='')):
  if x.get('action')=='delete': c.execute('DELETE FROM private_notes WHERE note_id=?',(x.get('note_id'),))
  elif x.get('action')=='add':
   now=datetime.datetime.now().isoformat(timespec='seconds'); c.execute('INSERT INTO private_notes VALUES(?,?,?,?,?,?)',(str(uuid.uuid4()),x.get('title',''),x.get('entity_ref',''),x.get('note_text',''),now,now))
 c.commit()
rows=[dict(zip(['note_id','title','entity_ref','note_text','created_at','updated_at'],r)) for r in c.execute('SELECT * FROM private_notes ORDER BY updated_at DESC')]; O.parent.mkdir(exist_ok=True); O.write_text(json.dumps({'records':rows},indent=2)); print('Notes:',len(rows))
