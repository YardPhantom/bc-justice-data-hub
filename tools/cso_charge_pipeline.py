#!/usr/bin/env python3
"""Permanent CSO charge-record inbox, cache and appearance linker.

CSO uses a human security image that prevents unattended automated searches.
This tool therefore prepares a capped lookup queue, imports user-saved CSO
records, caches them permanently, normalizes charges, and links them to daily
appearances. It never treats a charge or appearance as a conviction.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,re,sqlite3,sys
from datetime import datetime,timezone
from html import unescape
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'database'/'bc_justice.db'
INBOX=ROOT/'imports'/'cso-inbox'
ARCHIVE=ROOT/'imports'/'cso-archive'
DATA=ROOT/'data'
SEARCH_URL='https://justice.gov.bc.ca/cso/esearch/criminal/fileSearch.do'

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def norm_file(v): return re.sub(r'[^A-Z0-9]','',str(v or '').upper())
def norm_name(v): return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9 ]',' ',str(v or '').casefold())).strip()
def uid(*parts): return hashlib.sha256('|'.join(map(str,parts)).encode()).hexdigest()[:32]
def cols(c,t): return {r[1] for r in c.execute(f'PRAGMA table_info({t})')}

def ensure(c):
 c.executescript('''
 CREATE TABLE IF NOT EXISTS cso_case_files(
  cso_case_id TEXT PRIMARY KEY,court_file_number TEXT,normalized_file TEXT,courthouse_name TEXT,
  courthouse_slug TEXT,court_level TEXT,participant_names TEXT,opened_date TEXT,case_status TEXT,
  source_url TEXT,local_path TEXT,raw_sha256 TEXT,first_collected_at TEXT,last_collected_at TEXT,
  disposition_checked_at TEXT,access_state TEXT DEFAULT 'public',raw_json TEXT
 );
 CREATE INDEX IF NOT EXISTS idx_cso_file_norm ON cso_case_files(normalized_file);
 CREATE TABLE IF NOT EXISTS cso_charges(
  cso_charge_id TEXT PRIMARY KEY,cso_case_id TEXT,count_number TEXT,participant_name TEXT,
  offence_text TEXT,statute TEXT,section TEXT,charge_date TEXT,charge_status TEXT,
  finding TEXT,disposition TEXT,disposition_date TEXT,sentence_text TEXT,raw_json TEXT
 );
 CREATE INDEX IF NOT EXISTS idx_cso_charge_case ON cso_charges(cso_case_id);
 CREATE TABLE IF NOT EXISTS appearance_case_links(
  appearance_id TEXT,cso_case_id TEXT,match_tier TEXT,match_score REAL,matched_fields TEXT,
  linked_at TEXT,review_state TEXT DEFAULT 'unreviewed',PRIMARY KEY(appearance_id,cso_case_id)
 );
 CREATE TABLE IF NOT EXISTS cso_lookup_queue(
  queue_id TEXT PRIMARY KEY,court_file_number TEXT,normalized_file TEXT,participant_name TEXT,
  courthouse_name TEXT,appearance_date TEXT,priority INTEGER,status TEXT DEFAULT 'queued',
  reason TEXT,created_at TEXT,updated_at TEXT
 );
 CREATE INDEX IF NOT EXISTS idx_cso_queue_status ON cso_lookup_queue(status,priority);
 ''')
 c.commit()

def table_date_col(c):
 ac=cols(c,'daily_appearances')
 return next((x for x in ('list_date','appearance_date','date') if x in ac),None)

def prepare_queue(c,cap=250,refresh_dispositions=False):
 ensure(c); ac=cols(c,'daily_appearances'); dcol=table_date_col(c)
 needed=['appearance_id','court_file_number','participant_name','courthouse_name']
 if dcol: needed.append(dcol)
 if not all(x in ac for x in needed[:4]): return {'queued':0,'reason':'daily_appearances schema incomplete'}
 date_expr=dcol if dcol else "''"
 rows=c.execute(f'''SELECT appearance_id,court_file_number,participant_name,courthouse_name,{date_expr} appearance_date
 FROM daily_appearances WHERE trim(coalesce(court_file_number,''))<>''
 ORDER BY coalesce({date_expr},'') DESC''').fetchall()
 cached={r[0] for r in c.execute("SELECT normalized_file FROM cso_case_files WHERE normalized_file<>''")}
 if refresh_dispositions:
  cached={r[0] for r in c.execute("SELECT normalized_file FROM cso_case_files WHERE normalized_file<>'' AND coalesce(disposition_checked_at,'')<>''")}
 queued=0; seen=set()
 for r in rows:
  nf=norm_file(r[1])
  if not nf or nf in cached or nf in seen: continue
  seen.add(nf); qid=uid('cso-queue',nf)
  c.execute('''INSERT INTO cso_lookup_queue(queue_id,court_file_number,normalized_file,participant_name,courthouse_name,appearance_date,priority,status,reason,created_at,updated_at)
  VALUES(?,?,?,?,?,?,?,'queued',?,?,?) ON CONFLICT(queue_id) DO UPDATE SET participant_name=excluded.participant_name,courthouse_name=excluded.courthouse_name,appearance_date=excluded.appearance_date,updated_at=excluded.updated_at''',
  (qid,r[1],nf,r[2],r[3],r[4],queued+1,'No permanent CSO charge cache',now(),now()))
  queued+=1
  if queued>=cap: break
 c.commit(); export_queue(c,cap)
 return {'queued':queued,'cap':cap,'cachedCourtFiles':len(cached)}

def export_queue(c,cap=250):
 DATA.mkdir(exist_ok=True); INBOX.mkdir(parents=True,exist_ok=True)
 rows=[dict(zip([d[0] for d in cur.description],r)) for cur in [c.execute("SELECT * FROM cso_lookup_queue WHERE status='queued' ORDER BY priority,created_at LIMIT ?",(cap,))] for r in cur.fetchall()]
 for r in rows: r['officialSearchUrl']=SEARCH_URL
 (DATA/'cso-lookup-queue.json').write_text(json.dumps({'generatedAt':now(),'cap':cap,'records':rows},indent=2),encoding='utf-8')
 with (INBOX/'lookup-queue.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=['court_file_number','participant_name','courthouse_name','appearance_date','officialSearchUrl'])
  w.writeheader(); w.writerows([{k:r.get(k,'') for k in w.fieldnames} for r in rows])
 readme=INBOX/'README.txt'
 if not readme.exists(): readme.write_text('''CSO CHARGE RECORD INBOX\n\n1. Use lookup-queue.csv and the official CSO Traffic/Criminal file-number search.\n2. Complete CSO's security image manually.\n3. Save each file-detail page as HTML, or export a CSV/JSON record into this folder.\n4. Run: py -u tools\\cso_charge_pipeline.py all\n\nAccepted core fields: court_file_number, participant_name(s), courthouse, court_level, charges.\nCharge fields: offence_text/offence/charge, statute, section, charge_status, finding, disposition, disposition_date, sentence_text.\nFiles are archived after import and are not requested again unless --refresh-dispositions is used.\n''',encoding='utf-8')

def html_text(s): return re.sub(r'\s+',' ',unescape(re.sub(r'<[^>]+>',' ',s))).strip()
def parse_html(path):
 raw=path.read_text(encoding='utf-8',errors='ignore'); text=html_text(raw)
 def grab(labels):
  for lab in labels:
   m=re.search(rf'{lab}\s*[:#]?\s*([^|]{{2,120}}?)(?=\s+(?:File Number|Participant|Court Location|Registry|Charge|Offence|Appearance|Sentence|Disposition|Finding)\b|$)',text,re.I)
   if m:return m.group(1).strip()
  return ''
 file_no=grab(['File Number','Court File Number','Your file number']) or path.stem
 participant=grab(['Participant','Accused'])
 courthouse=grab(['Court Location','Registry Location','Registry'])
 charges=[]
 for m in re.finditer(r'(?:Charge|Offence)\s*[:#]?\s*(.{3,180}?)(?=\s+(?:Charge|Offence|Appearance|Sentence|Disposition|Finding)\b|$)',text,re.I):
  val=m.group(1).strip(' -:');
  if val and val.casefold() not in {x.get('offence_text','').casefold() for x in charges}: charges.append({'offence_text':val})
 return {'court_file_number':file_no,'participant_names':[participant] if participant else [],'courthouse':courthouse,'charges':charges,'source_url':SEARCH_URL,'raw_text':text[:20000]}

def parse_file(path):
 if path.suffix.lower()=='.json': return json.loads(path.read_text(encoding='utf-8-sig'))
 if path.suffix.lower()=='.csv':
  rows=list(csv.DictReader(path.open(encoding='utf-8-sig',newline='')))
  if not rows:return {}
  first=rows[0]; charges=[]
  for r in rows:
   off=r.get('offence_text') or r.get('offence') or r.get('charge')
   if off: charges.append({**r,'offence_text':off})
  return {**first,'participant_names':[first.get('participant_name','')],'charges':charges}
 if path.suffix.lower() in ('.html','.htm'): return parse_html(path)
 return {}

def import_inbox(c):
 ensure(c); INBOX.mkdir(parents=True,exist_ok=True); ARCHIVE.mkdir(parents=True,exist_ok=True)
 imported=charges_n=errors=0
 for p in sorted(INBOX.iterdir()):
  if p.name in ('README.txt','lookup-queue.csv') or p.suffix.lower() not in ('.json','.csv','.html','.htm'): continue
  try:
   obj=parse_file(p); file_no=obj.get('court_file_number') or obj.get('file_number')
   nf=norm_file(file_no)
   if not nf: raise ValueError('missing court_file_number')
   participants=obj.get('participant_names') or [obj.get('participant_name','')]
   if isinstance(participants,str): participants=[participants]
   cid=uid('cso-case',nf,obj.get('courthouse') or obj.get('courthouse_name',''))
   raw=p.read_bytes(); stamp=now(); local=f'imports/cso-archive/{p.name}'
   c.execute('''INSERT INTO cso_case_files(cso_case_id,court_file_number,normalized_file,courthouse_name,courthouse_slug,court_level,participant_names,opened_date,case_status,source_url,local_path,raw_sha256,first_collected_at,last_collected_at,disposition_checked_at,raw_json)
   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(cso_case_id) DO UPDATE SET participant_names=excluded.participant_names,last_collected_at=excluded.last_collected_at,disposition_checked_at=excluded.disposition_checked_at,raw_json=excluded.raw_json,local_path=excluded.local_path''',
   (cid,file_no,nf,obj.get('courthouse') or obj.get('courthouse_name',''),obj.get('courthouse_slug',''),obj.get('court_level','Provincial'),json.dumps([x for x in participants if x]),obj.get('opened_date',''),obj.get('case_status',''),obj.get('source_url',SEARCH_URL),local,hashlib.sha256(raw).hexdigest(),stamp,stamp,stamp if any((x.get('finding') or x.get('disposition')) for x in obj.get('charges',[])) else None,json.dumps(obj,ensure_ascii=False)))
   for i,ch in enumerate(obj.get('charges') or []):
    off=ch.get('offence_text') or ch.get('offence') or ch.get('charge')
    if not off: continue
    chid=uid('cso-charge',cid,ch.get('count_number',i+1),off)
    vals=(chid,cid,str(ch.get('count_number',i+1)),ch.get('participant_name') or (participants[0] if participants else ''),off,ch.get('statute',''),ch.get('section',''),ch.get('charge_date',''),ch.get('charge_status','alleged'),ch.get('finding',''),ch.get('disposition',''),ch.get('disposition_date',''),ch.get('sentence_text',''),json.dumps(ch,ensure_ascii=False))
    c.execute('INSERT OR REPLACE INTO cso_charges VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',vals); charges_n+=1
   c.execute("UPDATE cso_lookup_queue SET status='cached',updated_at=? WHERE normalized_file=?",(stamp,nf))
   target=ARCHIVE/p.name
   if target.exists(): target=ARCHIVE/f'{p.stem}-{uid(stamp)[:8]}{p.suffix}'
   p.replace(target); imported+=1
  except Exception as e:
   errors+=1; print(f'CSO inbox import failed {p.name}: {e}',file=sys.stderr)
 c.commit(); return {'filesImported':imported,'chargesImported':charges_n,'errors':errors}

def ensure_normalized_case(c,cf):
 case_cols=cols(c,'cases'); cid=uid('case','cso',cf['normalized_file'],cf['courthouse_slug'] or cf['courthouse_name'])
 payload={'case_id':cid,'court_file_number':cf['court_file_number'],'court_level':cf['court_level'] or 'Provincial','courthouse_slug':cf['courthouse_slug'],'case_title':', '.join(json.loads(cf['participant_names'] or '[]')),'legal_status':'charged','verification_state':'source-verified','source_url':cf['source_url'],'retrieved_at':cf['last_collected_at'],'notes':'Imported from locally cached CSO public court record.'}
 keys=[k for k in payload if k in case_cols]
 c.execute(f"INSERT OR IGNORE INTO cases({','.join(keys)}) VALUES({','.join('?'*len(keys))})",tuple(payload[k] for k in keys))
 return cid

def link(c):
 ensure(c); linked=normcharges=0
 c.row_factory=sqlite3.Row
 files=list(c.execute('SELECT * FROM cso_case_files'))
 byfile={r['normalized_file']:r for r in files}
 ac=cols(c,'daily_appearances'); dcol=table_date_col(c)
 for a in c.execute(f"SELECT appearance_id,court_file_number,participant_name,courthouse_name,{dcol or "''"} appearance_date FROM daily_appearances WHERE trim(coalesce(court_file_number,''))<>''"):
  cf=byfile.get(norm_file(a['court_file_number']))
  if not cf: continue
  names=json.loads(cf['participant_names'] or '[]'); an=norm_name(a['participant_name']); name_exact=an and any(an==norm_name(n) for n in names)
  court_match=norm_name(a['courthouse_name']) and norm_name(a['courthouse_name']) in norm_name(cf['courthouse_name'])
  tier='Confirmed' if name_exact and court_match else ('Likely' if name_exact else 'Non Verified')
  score={'Confirmed':1.0,'Likely':.85,'Non Verified':.45}[tier]; fields=['exact court file']+(['accused name'] if name_exact else [])+(['courthouse'] if court_match else [])
  c.execute('INSERT OR REPLACE INTO appearance_case_links VALUES(?,?,?,?,?,?,?)',(a['appearance_id'],cf['cso_case_id'],tier,score,json.dumps(fields),now(),'unreviewed')); linked+=1
  case_id=ensure_normalized_case(c,cf)
  for ch in c.execute('SELECT * FROM cso_charges WHERE cso_case_id=?',(cf['cso_case_id'],)).fetchall():
   charge_id=uid('charge',case_id,ch['cso_charge_id'])
   c.execute('''INSERT OR REPLACE INTO charges(charge_id,case_id,offence_text,statute,section,charge_date,charge_status,disposition,disposition_date,source_document_id)
   VALUES(?,?,?,?,?,?,?,?,?,?)''',(charge_id,case_id,ch['offence_text'],ch['statute'],ch['section'],ch['charge_date'],ch['charge_status'] or 'alleged',ch['disposition'] or ch['finding'],ch['disposition_date'],cf['cso_case_id'])); normcharges+=1
 c.commit(); return {'appearanceLinks':linked,'normalizedCharges':normcharges}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('cmd',choices=['queue','import','link','all']); ap.add_argument('--cap',type=int,default=250); ap.add_argument('--refresh-dispositions',action='store_true'); a=ap.parse_args()
 DB.parent.mkdir(exist_ok=True); c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; ensure(c)
 out={}
 if a.cmd in ('queue','all'): out['queue']=prepare_queue(c,min(max(a.cap,1),250),a.refresh_dispositions)
 if a.cmd in ('import','all'): out['import']=import_inbox(c)
 if a.cmd in ('link','all'): out['link']=link(c)
 print(json.dumps(out,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
