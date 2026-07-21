#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json, os, re, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
SCRIPT_DIR=Path(__file__).resolve().parent
ROOT=SCRIPT_DIR.parent
DB=ROOT/'database'/'bc_justice.db'
def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def setup(c):
 c.executescript('''
 CREATE TABLE IF NOT EXISTS review_actions(action_id INTEGER PRIMARY KEY AUTOINCREMENT,action_type TEXT,entity_id TEXT,decision TEXT,notes TEXT,applied_at TEXT,raw_json TEXT);
 CREATE TABLE IF NOT EXISTS case_record_history(history_id INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT,record_type TEXT,record_key TEXT,action_type TEXT,payload_json TEXT,recorded_at TEXT,notes TEXT);
 CREATE TABLE IF NOT EXISTS dismissed_review_archive(archive_id INTEGER PRIMARY KEY AUTOINCREMENT,review_id TEXT,entity_type TEXT,entity_id TEXT,reason TEXT,severity TEXT,source_document_id TEXT,original_created_at TEXT,dismissed_at TEXT NOT NULL,dismissal_notes TEXT,action_json TEXT,UNIQUE(review_id),UNIQUE(entity_type,entity_id,reason));
 CREATE TRIGGER IF NOT EXISTS prevent_dismissed_review_requeue BEFORE INSERT ON review_queue WHEN EXISTS(SELECT 1 FROM dismissed_review_archive d WHERE d.review_id=NEW.review_id OR (COALESCE(d.entity_type,'')=COALESCE(NEW.entity_type,'') AND COALESCE(d.entity_id,'')=COALESCE(NEW.entity_id,'') AND COALESCE(d.reason,'')=COALESCE(NEW.reason,''))) BEGIN SELECT RAISE(IGNORE); END;
 '''); c.commit()
def load(path):
 if path.suffix.lower()=='.json':
  d=json.loads(path.read_text(encoding='utf-8-sig')); return d if isinstance(d,list) else d.get('actions',[])
 with path.open('r',encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def norm_name(value): return re.sub(r'[^a-z0-9]+',' ',str(value or '').lower()).strip()
def split_values(value):
 return [x.strip() for x in re.split(r'[;\n|]+',str(value or '')) if x.strip()]

def archive_review_rows(c, where_sql, params, notes, action):
 stamp=now(); rows=c.execute(f'SELECT * FROM review_queue WHERE {where_sql}',params).fetchall()
 for row in rows:
  d=dict(row)
  c.execute('''INSERT OR IGNORE INTO dismissed_review_archive(review_id,entity_type,entity_id,reason,severity,source_document_id,original_created_at,dismissed_at,dismissal_notes,action_json) VALUES(?,?,?,?,?,?,?,?,?,?)''',(d.get('review_id'),d.get('entity_type'),d.get('entity_id'),d.get('reason'),d.get('severity'),d.get('source_document_id'),d.get('created_at'),stamp,notes or 'Review dismissed',json.dumps(action,ensure_ascii=False)))
 return len(rows)
def ensure_judgment_schema(c):
 c.executescript('''
 CREATE TABLE IF NOT EXISTS people(person_id TEXT PRIMARY KEY,display_name TEXT NOT NULL,normalized_name TEXT,date_of_birth TEXT,identity_confidence REAL DEFAULT 0,review_required INTEGER DEFAULT 1,created_at TEXT,updated_at TEXT);
 CREATE TABLE IF NOT EXISTS cases(case_id TEXT PRIMARY KEY,court_file_number TEXT,citation TEXT,court_level TEXT,courthouse_slug TEXT,case_title TEXT,opened_date TEXT,closed_date TEXT,legal_status TEXT DEFAULT 'unknown',final_outcome TEXT,outcome_date TEXT,verification_state TEXT DEFAULT 'review',publication_restriction INTEGER DEFAULT 0,source_document_id TEXT,source_url TEXT,retrieved_at TEXT,notes TEXT);
 CREATE TABLE IF NOT EXISTS case_people(case_id TEXT,person_id TEXT,role TEXT DEFAULT 'accused',PRIMARY KEY(case_id,person_id,role));
 CREATE TABLE IF NOT EXISTS charges(charge_id TEXT PRIMARY KEY,case_id TEXT,offence_text TEXT,statute TEXT,section TEXT,charge_date TEXT,charge_status TEXT DEFAULT 'alleged',disposition TEXT,disposition_date TEXT,source_document_id TEXT);
 CREATE TABLE IF NOT EXISTS outcomes(outcome_id TEXT PRIMARY KEY,case_id TEXT,outcome_type TEXT NOT NULL,outcome_date TEXT,sentence_text TEXT,appeal_status TEXT,source_document_id TEXT,verified INTEGER DEFAULT 0,verified_at TEXT,notes TEXT);
 ''')
def audit_case_rows(c,case_id,record_type,rows,action_type,notes=''):
 for row in rows:
  d=dict(row)
  record_key=str(d.get('charge_id') or d.get('outcome_id') or d.get('person_id') or d.get('role') or '')
  c.execute('INSERT INTO case_record_history(case_id,record_type,record_key,action_type,payload_json,recorded_at,notes) VALUES(?,?,?,?,?,?,?)',(case_id,record_type,record_key,action_type,json.dumps(d,ensure_ascii=False),now(),notes))

def snapshot_case_state(c,case_id,action_type,notes=''):
 audit_case_rows(c,case_id,'case_people',c.execute('SELECT * FROM case_people WHERE case_id=?',(case_id,)).fetchall(),action_type,notes)
 audit_case_rows(c,case_id,'charges',c.execute('SELECT * FROM charges WHERE case_id=?',(case_id,)).fetchall(),action_type,notes)
 audit_case_rows(c,case_id,'outcomes',c.execute('SELECT * FROM outcomes WHERE case_id=?',(case_id,)).fetchall(),action_type,notes)

def verify_judgment(c,a,notes):
 jid=(a.get('target_entity_id') or '').strip()
 if not jid: raise ValueError('Verify judgment requires target_entity_id')
 row=c.execute('SELECT * FROM published_judgments WHERE judgment_id=?',(jid,)).fetchone()
 if not row: raise ValueError('judgment not found')
 names=split_values(a.get('names')); charges=split_values(a.get('charges')); outcome=(a.get('outcome') or '').strip().lower(); sentence=(a.get('sentence') or '').strip(); outcome_date=(a.get('outcome_date') or '').strip() or row['decision_date']; file_no=(a.get('case_file_number') or '').strip()
 if not names: raise ValueError('Verify judgment requires at least one reviewed name')
 if not charges: raise ValueError('Verify judgment requires at least one reviewed charge/offence')
 if not outcome: raise ValueError('Verify judgment requires a reviewed outcome')
 ensure_judgment_schema(c)
 case_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'judgment-case:{jid}'))
 legal='convicted' if outcome=='convicted' else outcome
 c.execute('''INSERT INTO cases(case_id,court_file_number,citation,court_level,case_title,closed_date,legal_status,final_outcome,outcome_date,verification_state,source_url,retrieved_at,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
 ON CONFLICT(case_id) DO UPDATE SET court_file_number=excluded.court_file_number,citation=excluded.citation,court_level=excluded.court_level,case_title=excluded.case_title,closed_date=excluded.closed_date,legal_status=excluded.legal_status,final_outcome=excluded.final_outcome,outcome_date=excluded.outcome_date,verification_state='verified',source_url=excluded.source_url,retrieved_at=excluded.retrieved_at,notes=excluded.notes''',(case_id,file_no,row['citation'],row['court_level'],row['case_title'],outcome_date,legal,outcome,outcome_date,'verified',row['source_url'],now(),notes or 'Verified from published judgment'))
 snapshot_case_state(c,case_id,'replace_from_verified_judgment',notes)
 c.execute('DELETE FROM case_people WHERE case_id=?',(case_id,)); c.execute('DELETE FROM charges WHERE case_id=?',(case_id,)); c.execute('DELETE FROM outcomes WHERE case_id=?',(case_id,))
 for name in names:
  pid=str(uuid.uuid5(uuid.NAMESPACE_URL,'PERSON|'+norm_name(name)))
  c.execute('''INSERT INTO people(person_id,display_name,normalized_name,identity_confidence,review_required,created_at,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(person_id) DO UPDATE SET display_name=excluded.display_name,normalized_name=excluded.normalized_name,identity_confidence=1,review_required=0,updated_at=excluded.updated_at''',(pid,name,norm_name(name),1,0,now(),now()))
  c.execute('INSERT OR IGNORE INTO case_people(case_id,person_id,role) VALUES(?,?,?)',(case_id,pid,'accused'))
 for offence in charges:
  charge_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'{case_id}|charge|{norm_name(offence)}'))
  c.execute('INSERT INTO charges(charge_id,case_id,offence_text,charge_status,disposition,disposition_date) VALUES(?,?,?,?,?,?)',(charge_id,case_id,offence,'proven' if outcome=='convicted' else 'resolved',outcome,outcome_date))
 outcome_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'{case_id}|outcome|{outcome}|{outcome_date}'))
 c.execute('INSERT INTO outcomes(outcome_id,case_id,outcome_type,outcome_date,sentence_text,verified,verified_at,notes) VALUES(?,?,?,?,?,?,?,?)',(outcome_id,case_id,outcome,outcome_date,sentence,1,now(),notes))
 c.execute("UPDATE published_judgments SET outcome_type=?,sentence_text=?,verification_state='verified' WHERE judgment_id=?",(outcome,sentence,jid))
 c.execute("UPDATE review_queue SET status='resolved',resolved_at=?,resolution_notes=? WHERE entity_type='published_judgment' AND entity_id=?",(now(),notes or 'Verified judgment and published searchable fields',jid))

def judgment_review(c,a,decision,notes):
 jid=(a.get('target_entity_id') or '').strip()
 if decision=='verify': return verify_judgment(c,a,notes)
 if not jid: raise ValueError('judgment review requires target_entity_id')
 if decision=='needs_correction':
  c.execute("UPDATE published_judgments SET verification_state='needs_correction' WHERE judgment_id=?",(jid,))
  c.execute("UPDATE review_queue SET status='open',resolved_at=NULL,resolution_notes=? WHERE entity_type='published_judgment' AND entity_id=?",(notes or 'Needs correction',jid))
 elif decision=='dismiss':
  archive_review_rows(c,"entity_type='published_judgment' AND entity_id=?",(jid,),notes,a)
  c.execute("UPDATE published_judgments SET verification_state='dismissed' WHERE judgment_id=?",(jid,))
  c.execute("UPDATE review_queue SET status='resolved',resolved_at=?,resolution_notes=? WHERE entity_type='published_judgment' AND entity_id=?",(now(),notes or 'Review dismissed',jid))
 else: raise ValueError(f'unknown judgment decision: {decision}')

def merge_people(c,keep,remove,notes):
 if not keep or not remove or keep==remove: raise ValueError('merge requires distinct keep_person_id and remove_person_id')
 if not c.execute('SELECT 1 FROM people WHERE person_id=?',(keep,)).fetchone() or not c.execute('SELECT 1 FROM people WHERE person_id=?',(remove,)).fetchone(): raise ValueError('person not found')
 c.execute('INSERT OR IGNORE INTO case_people(case_id,person_id,role) SELECT case_id,?,role FROM case_people WHERE person_id=?',(keep,remove))
 c.execute('DELETE FROM case_people WHERE person_id=?',(remove,)); c.execute('DELETE FROM people WHERE person_id=?',(remove,))
 c.execute("UPDATE identity_candidates SET status='merged' WHERE (person_a=? AND person_b=?) OR (person_a=? AND person_b=?)",(keep,remove,remove,keep))
 c.execute("UPDATE review_queue SET status='resolved',resolved_at=?,resolution_notes=? WHERE entity_type='identity_candidate' AND status='open' AND entity_id IN (SELECT candidate_id FROM identity_candidates WHERE status='merged')",(now(),notes))
def identity_action(c,a,decision,notes):
 ensure_judgment_schema(c)
 c.executescript("""CREATE TABLE IF NOT EXISTS person_aliases(alias_id TEXT PRIMARY KEY,person_id TEXT NOT NULL,alias_text TEXT NOT NULL,normalized_alias TEXT NOT NULL,alias_type TEXT DEFAULT 'manual',source_document_id TEXT,verified INTEGER DEFAULT 0,created_at TEXT,UNIQUE(person_id,normalized_alias));CREATE TABLE IF NOT EXISTS person_identity_decisions(decision_id TEXT PRIMARY KEY,pair_key TEXT,person_a TEXT,person_b TEXT,decision TEXT NOT NULL,notes TEXT,reviewer TEXT,source TEXT,active INTEGER DEFAULT 1,decided_at TEXT,updated_at TEXT);""")
 dcols={r[1] for r in c.execute('PRAGMA table_info(person_identity_decisions)')}
 for spec in ['pair_key TEXT','reviewer TEXT','source TEXT','active INTEGER DEFAULT 1','updated_at TEXT']:
  if spec.split()[0] not in dcols:c.execute(f'ALTER TABLE person_identity_decisions ADD COLUMN {spec}')
 c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_identity_decision_pair ON person_identity_decisions(pair_key) WHERE active=1')
 eid=(a.get('entity_id') or '').strip(); pid=(a.get('person_id') or '').strip(); reviewer=(a.get('reviewer') or '').strip(); source=(a.get('source') or 'identity-review').strip()
 def remember(pa,pb,value):
  if not pa or not pb:return
  pair='|'.join(sorted((pa,pb))); stamp=now(); existing=c.execute('SELECT decision_id FROM person_identity_decisions WHERE pair_key=? AND COALESCE(active,1)=1',(pair,)).fetchone()
  if existing:c.execute('UPDATE person_identity_decisions SET person_a=?,person_b=?,decision=?,notes=?,reviewer=?,source=?,updated_at=? WHERE decision_id=?',(pa,pb,value,notes,reviewer,source,stamp,existing['decision_id']))
  else:c.execute('INSERT INTO person_identity_decisions(decision_id,pair_key,person_a,person_b,decision,notes,reviewer,source,active,decided_at,updated_at) VALUES(?,?,?,?,?,?,?,?,1,?,?)',(str(uuid.uuid4()),pair,pa,pb,value,notes,reviewer,source,stamp,stamp))
 if decision in ('merge','same_person'):
  keep=(a.get('keep_person_id') or '').strip(); remove=(a.get('remove_person_id') or '').strip(); remember(keep,remove,'same_person'); merge_people(c,keep,remove,notes)
 elif decision in ('not_match','different_person'):
  row=c.execute('SELECT person_a,person_b FROM identity_candidates WHERE candidate_id=?',(eid,)).fetchone()
  c.execute("UPDATE identity_candidates SET status='not_match' WHERE candidate_id=?",(eid,)); remember(row['person_a'] if row else None,row['person_b'] if row else None,'different_person')
 elif decision=='add_alias':
  alias=(a.get('alias_text') or '').strip()
  if not pid or not alias: raise ValueError('add_alias requires person_id and alias_text')
  aid=str(uuid.uuid5(uuid.NAMESPACE_URL,'alias|'+pid+'|'+norm_name(alias)))
  c.execute('INSERT OR REPLACE INTO person_aliases VALUES(?,?,?,?,?,?,?,?)',(aid,pid,alias,norm_name(alias),'manual',None,1,now()))
 elif decision=='split_case':
  case_id=(a.get('case_id') or '').strip()
  if not pid or not case_id: raise ValueError('split_case requires person_id and case_id')
  new_id=str(uuid.uuid4()); old=c.execute('SELECT * FROM people WHERE person_id=?',(pid,)).fetchone()
  if not old: raise ValueError('person not found')
  c.execute('INSERT INTO people(person_id,display_name,normalized_name,identity_confidence,review_required,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(new_id,old['display_name'],old['normalized_name'],.3,1,now(),now()))
  c.execute('UPDATE case_people SET person_id=? WHERE person_id=? AND case_id=?',(new_id,pid,case_id))
 else: raise ValueError('unknown identity decision: '+decision)

def apply(c,a):
 typ=(a.get('action_type') or '').strip(); eid=(a.get('entity_id') or '').strip(); decision=(a.get('decision') or '').strip().lower(); notes=(a.get('notes') or '').strip()
 if typ=='judgment_review':
  judgment_review(c,a,decision,notes)
 elif typ=='identity':
  identity_action(c,a,decision,notes)
 elif typ=='review':
  status='resolved' if decision in ('resolve','approved','verified','dismiss') else 'open'
  if decision=='dismiss': archive_review_rows(c,'review_id=?',(eid,),notes,a)
  c.execute('UPDATE review_queue SET status=?,resolved_at=?,resolution_notes=? WHERE review_id=?',(status,now() if status=='resolved' else None,notes,eid))
 elif typ=='duplicate':
  if decision=='merge': merge_people(c,(a.get('keep_person_id') or '').strip(),(a.get('remove_person_id') or '').strip(),notes)
  else: c.execute('UPDATE identity_candidates SET status=? WHERE candidate_id=?',('not_match' if decision in ('reject','not_match') else 'verified_match',eid))
 elif typ=='case_link':
  c.execute('UPDATE case_links SET verified=? WHERE link_id=?',(1 if decision in ('approve','verified') else -1,eid))
  c.execute("UPDATE review_queue SET status='resolved',resolved_at=?,resolution_notes=? WHERE entity_type='case_link' AND entity_id=?",(now(),notes or decision,eid))
 elif typ=='pdf_correction':
  c.execute("UPDATE source_documents SET notes=TRIM(COALESCE(notes,'') || CASE WHEN COALESCE(notes,'')='' THEN '' ELSE char(10) END || ?), parse_status=CASE WHEN ?='approve' THEN 'corrected' ELSE parse_status END WHERE document_id=?",(notes,decision,eid))
  c.execute("UPDATE review_queue SET status='resolved',resolved_at=?,resolution_notes=? WHERE source_document_id=?",(now(),notes,eid))
 else: raise ValueError(f'unknown action_type: {typ}')
 c.execute('INSERT INTO review_actions(action_type,entity_id,decision,notes,applied_at,raw_json) VALUES(?,?,?,?,?,?)',(typ,eid,decision,notes,now(),json.dumps(a,ensure_ascii=False)))
def resolve_action_file(value):
 requested=Path(value).expanduser()
 candidates=[]
 profile_value=os.environ.get('USERPROFILE') or os.environ.get('HOME')
 profile=Path(profile_value).expanduser() if profile_value else None
 if requested.is_absolute():
  candidates.append(requested)
 else:
  candidates.extend((SCRIPT_DIR/requested, Path.cwd()/requested, ROOT/requested))
  if profile:
   candidates.extend((profile/'Downloads'/requested.name, profile/'OneDrive'/'Downloads'/requested.name))
 for candidate in candidates:
  if candidate.exists(): return candidate.resolve()
 # When the browser adds a suffix, use the newest matching export from Downloads.
 if profile:
  matches=[]
  for folder in (profile/'Downloads', profile/'OneDrive'/'Downloads'):
   if folder.exists(): matches.extend(folder.glob(f'{requested.stem}*{requested.suffix}'))
  if matches: return max(matches,key=lambda item:item.stat().st_mtime).resolve()
 checked='\n - '.join(str(item) for item in candidates)
 raise SystemExit(f'Action file not found. Checked:\n - {checked}\nDownload/export review-actions.csv, or pass its full path.')
def main():
 p=argparse.ArgumentParser(); p.add_argument('file',nargs='?',default='review-actions.csv'); args=p.parse_args(); path=resolve_action_file(args.file)
 print(f'Using action file: {path}')
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; setup(c); actions=load(path); ok=0; errors=[]
 for i,a in enumerate(actions,2):
  try:
   with c: apply(c,a); ok+=1
  except Exception as e: errors.append(f'row {i}: {e}')
 print(f'Applied {ok} review actions.');
 if errors: print('\n'.join(errors)); return 1
 return 0
if __name__=='__main__': raise SystemExit(main())
