#!/usr/bin/env python3
"""Central person-mention registry for BC Justice Data Hub.

A mention records what a source says about a name. It never upgrades an
appearance, allegation, or charge into a conviction.
"""
from __future__ import annotations
import hashlib, re, sqlite3
from datetime import datetime, timezone

SCHEMA = '''
CREATE TABLE IF NOT EXISTS person_mentions(
 mention_id TEXT PRIMARY KEY,
 person_id TEXT,
 exact_name TEXT NOT NULL,
 normalized_name TEXT NOT NULL,
 role TEXT DEFAULT 'unknown',
 legal_status TEXT DEFAULT 'unknown',
 source_entity_type TEXT NOT NULL,
 source_entity_id TEXT NOT NULL,
 source_document_id TEXT,
 source_url TEXT,
 event_date TEXT,
 court_file_number TEXT,
 court TEXT,
 location TEXT,
 offence_text TEXT,
 verification_state TEXT DEFAULT 'review',
 confidence REAL DEFAULT 0.5,
 raw_context TEXT,
 created_at TEXT,
 updated_at TEXT,
 UNIQUE(normalized_name,source_entity_type,source_entity_id,role)
);
CREATE INDEX IF NOT EXISTS idx_person_mentions_name ON person_mentions(normalized_name);
CREATE INDEX IF NOT EXISTS idx_person_mentions_person ON person_mentions(person_id);
CREATE INDEX IF NOT EXISTS idx_person_mentions_source ON person_mentions(source_entity_type,source_entity_id);
'''

NON_PERSON_TOKENS={
 'r','regina','rex','king','queen','crown','appellant','respondent','applicant',
 'province','british','columbia','canada','court','justice','unknown','unnamed'
}
ROLE_ALIASES={
 'accused':'accused','defendant':'accused','charged':'accused','offender':'accused',
 'appellant':'party','respondent':'party','applicant':'party','plaintiff':'party',
 'complainant':'complainant','victim':'complainant','witness':'witness',
 'counsel':'counsel','lawyer':'counsel','judge':'judge','justice':'judge'
}
STATUS_ALIASES={
 'appearance':'scheduled_appearance','scheduled':'scheduled_appearance',
 'scheduled appearance':'scheduled_appearance','charge':'charged','charges':'charged',
 'not guilty':'acquitted','not_guilty':'acquitted','charges stayed':'stayed'
}

def now():
 return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def normalize_name(value):
 text=' '.join(str(value or '').replace('\u00a0',' ').split()).strip(' ,;:-')
 if not text: return ''
 if ',' in text and text.count(',')==1:
  last, first=[part.strip() for part in text.split(',',1)]
  if first and last: text=f'{first} {last}'
 text=re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ' -]+",' ',text)
 return ' '.join(text.casefold().split())

def display_name(value):
 text=' '.join(str(value or '').split()).strip(' ,;:-')
 if ',' in text and text.count(',')==1:
  last,first=[part.strip() for part in text.split(',',1)]
  if first and last: return f'{first} {last}'
 return text

def plausible_name(value):
 norm=normalize_name(value)
 bits=norm.split()
 if not bits or len(norm)<3 or len(bits)>7: return False
 if all(bit in NON_PERSON_TOKENS for bit in bits): return False
 if any(len(bit)==1 and bit not in {'j','r'} for bit in bits): return False
 return any(bit not in NON_PERSON_TOKENS for bit in bits)

def normalize_role(value):
 key=str(value or '').strip().casefold()
 return ROLE_ALIASES.get(key,key or 'unknown')

def normalize_status(value):
 key=str(value or '').strip().casefold().replace('_',' ')
 return STATUS_ALIASES.get(key,key.replace(' ','_') or 'unknown')

def ensure_schema(c: sqlite3.Connection):
 c.executescript(SCHEMA)

def stable_person_id(normalized):
 return hashlib.sha256(('PERSON|'+normalized).encode('utf-8')).hexdigest()[:32]

def record_mention(c: sqlite3.Connection, *, name, source_entity_type, source_entity_id,
 role='unknown', legal_status='unknown', source_document_id='', source_url='', event_date='',
 court_file_number='', court='', location='', offence_text='', verification_state='review',
 confidence=0.5, raw_context='', person_id=None):
 ensure_schema(c)
 exact=display_name(name); normalized=normalize_name(exact)
 if not plausible_name(exact): return None
 role=normalize_role(role); status=normalize_status(legal_status)
 pid=person_id or stable_person_id(normalized)
 stamp=now()
 mention_key='|'.join((normalized,str(source_entity_type),str(source_entity_id),role))
 mention_id=hashlib.sha256(mention_key.encode('utf-8')).hexdigest()[:40]
 c.execute('''INSERT INTO person_mentions(
  mention_id,person_id,exact_name,normalized_name,role,legal_status,source_entity_type,
  source_entity_id,source_document_id,source_url,event_date,court_file_number,court,
  location,offence_text,verification_state,confidence,raw_context,created_at,updated_at)
  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
  ON CONFLICT(normalized_name,source_entity_type,source_entity_id,role) DO UPDATE SET
   person_id=COALESCE(person_mentions.person_id,excluded.person_id), exact_name=excluded.exact_name,
   legal_status=excluded.legal_status, source_document_id=excluded.source_document_id,
   source_url=excluded.source_url,event_date=excluded.event_date,
   court_file_number=excluded.court_file_number,court=excluded.court,location=excluded.location,
   offence_text=excluded.offence_text,verification_state=excluded.verification_state,
   confidence=MAX(person_mentions.confidence,excluded.confidence),raw_context=excluded.raw_context,
   updated_at=excluded.updated_at''',
  (mention_id,pid,exact,normalized,role,status,str(source_entity_type),str(source_entity_id),
   source_document_id or '',source_url or '',event_date or '',court_file_number or '',court or '',
   location or '',offence_text or '',verification_state or 'review',float(confidence or 0.5),
   raw_context or '',stamp,stamp))
 c.execute('''INSERT INTO people(person_id,display_name,normalized_name,identity_confidence,
  review_required,created_at,updated_at) VALUES(?,?,?,?,?,?,?)
  ON CONFLICT(person_id) DO UPDATE SET display_name=CASE WHEN length(excluded.display_name)>length(people.display_name) THEN excluded.display_name ELSE people.display_name END,
  identity_confidence=MAX(COALESCE(people.identity_confidence,0),excluded.identity_confidence),updated_at=excluded.updated_at''',
  (pid,exact,normalized,float(confidence or 0.5),0 if verification_state=='verified' else 1,stamp,stamp))
 return mention_id

def names_from_judgment_title(title):
 text=' '.join(str(title or '').split())
 if not text: return []
 parts=re.split(r'\s+(?:v\.?|versus)\s+',text,flags=re.I)
 if len(parts)<2: return []
 names=[]
 for part in parts:
  candidate=part.strip(' ,;:-')
  if normalize_name(candidate) in {'r','regina','rex','the king','the queen','crown'}: continue
  if plausible_name(candidate): names.append(candidate)
 return names

def rebuild_from_normalized_sources(c: sqlite3.Connection):
 """Harvest mentions from normalized tables after any collector/import run."""
 ensure_schema(c)
 tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
 count=0
 if {'cases','case_people','people'}.issubset(tables):
  query='''SELECT c.case_id,c.court_file_number,c.case_title,c.legal_status,c.final_outcome,
   c.outcome_date,c.opened_date,c.verification_state,c.source_document_id,c.source_url,
   c.court_level,c.courthouse_slug,p.person_id,p.display_name,cp.role,
   (SELECT GROUP_CONCAT(DISTINCT offence_text) FROM charges ch WHERE ch.case_id=c.case_id) offences
   FROM cases c JOIN case_people cp ON cp.case_id=c.case_id JOIN people p ON p.person_id=cp.person_id'''
  for r in c.execute(query):
   if record_mention(c,name=r['display_name'],person_id=r['person_id'],source_entity_type='case',
    source_entity_id=r['case_id'],role=r['role'],legal_status=r['final_outcome'] or r['legal_status'],
    source_document_id=r['source_document_id'],source_url=r['source_url'],
    event_date=r['outcome_date'] or r['opened_date'],court_file_number=r['court_file_number'],
    court=r['court_level'],location=str(r['courthouse_slug'] or '').replace('-',' ').title(),
    offence_text=r['offences'],verification_state=r['verification_state'],confidence=0.9 if r['verification_state']=='verified' else 0.65,
    raw_context=r['case_title']): count+=1
 if 'daily_appearances' in tables:
  cols={r[1] for r in c.execute('PRAGMA table_info(daily_appearances)')}
  wanted=[x for x in ('appearance_id','participant_name','court_file_number','courthouse_name','courtroom','appearance_date','list_date','appearance_reason','document_id','document_version_id') if x in cols]
  if 'participant_name' in wanted:
   for r in c.execute(f"SELECT {','.join(wanted)} FROM daily_appearances"):
    d=dict(r); name=d.get('participant_name')
    if record_mention(c,name=name,source_entity_type='court_list',source_entity_id=d.get('appearance_id'),
     role='accused',legal_status='scheduled_appearance',source_document_id=d.get('document_id') or d.get('document_version_id') or '',
     event_date=d.get('appearance_date') or d.get('list_date') or '',court_file_number=d.get('court_file_number') or '',
     location=d.get('courthouse_name') or '',verification_state='review',confidence=0.55,
     raw_context=d.get('appearance_reason') or ''): count+=1
 # Source-body harvesting supplements normalized participants without changing legal status.
 if 'police_reports' in tables:
  count+=_harvest_text_table(c,'police_reports','report_id',('title','raw_text'),source_type='police_report',title_col='title',url_col='source_url',date_col='retrieved_at',status='alleged',role='unknown',confidence=.5)
 if 'prosecution_reports' in tables:
  count+=_harvest_text_table(c,'prosecution_reports','report_id',('title','raw_text'),source_type='prosecution_report',title_col='title',url_col='source_url',date_col='retrieved_at',status='unknown',role='unknown',confidence=.5)
 if 'corrections_oversight_documents' in tables:
  count+=_harvest_text_table(c,'corrections_oversight_documents','document_id',('title','summary','raw_text'),source_type='corrections_document',title_col='title',url_col='source_url',date_col='published_date',status='unknown',role='unknown',confidence=.5)
 if 'published_judgments' in tables:
  cols={r[1] for r in c.execute('PRAGMA table_info(published_judgments)')}
  wanted=[x for x in ('judgment_id','case_name','case_title','title','citation','court_file_number','court','court_level','decision_date','source_url','verification_state','outcome','outcome_type','summary','decision_text','raw_metadata','publication_flags') if x in cols]
  # Build exact cross-source links once. Citation and court-file matches are strong enough
  # to enrich a judgment without relying on name similarity alone.
  citation_people={}; file_people={}
  if {'cases','case_people','people'}.issubset(tables):
   for row in c.execute('''SELECT c.citation,c.court_file_number,c.case_id,c.final_outcome,c.legal_status,
    c.verification_state,c.source_url,c.court_level,c.courthouse_slug,p.person_id,p.display_name,cp.role,
    (SELECT GROUP_CONCAT(DISTINCT offence_text) FROM charges ch WHERE ch.case_id=c.case_id) offences
    FROM cases c JOIN case_people cp ON cp.case_id=c.case_id JOIN people p ON p.person_id=cp.person_id'''):
    item=dict(row)
    cit=' '.join(str(item.get('citation') or '').casefold().split())
    fil=re.sub(r'[^a-z0-9]','',str(item.get('court_file_number') or '').casefold())
    if cit: citation_people.setdefault(cit,[]).append(item)
    if fil: file_people.setdefault(fil,[]).append(item)
  if 'daily_appearances' in tables:
   acols={r[1] for r in c.execute('PRAGMA table_info(daily_appearances)')}
   if {'participant_name','court_file_number'}.issubset(acols):
    date_col=next((x for x in ('appearance_date','list_date','event_date','scheduled_date','court_date','date') if x in acols),None)
    court_col=next((x for x in ('courthouse_name','courthouse','court_location','location') if x in acols),None)
    select_cols=['participant_name','court_file_number']
    if court_col: select_cols.append(court_col)
    if date_col and date_col not in select_cols: select_cols.append(date_col)
    for row in c.execute(f"SELECT {','.join(select_cols)} FROM daily_appearances"):
     item=dict(row); fil=re.sub(r'[^a-z0-9]','',str(item.get('court_file_number') or '').casefold())
     if fil and plausible_name(item.get('participant_name')):
      item.update({'person_id':stable_person_id(normalize_name(item['participant_name'])),'display_name':item['participant_name'],
       'role':'accused','final_outcome':'','legal_status':'scheduled_appearance','verification_state':'review',
       'source_url':'today-court.html','court_level':'','courthouse_slug':item.get(court_col) if court_col else '',
       'appearance_date':item.get(date_col) if date_col else '','offences':''})
      file_people.setdefault(fil,[]).append(item)
  if wanted:
   for r in c.execute(f"SELECT {','.join(wanted)} FROM published_judgments"):
    d=dict(r); jid=d.get('judgment_id') or d.get('citation'); title=d.get('case_name') or d.get('case_title') or d.get('title') or ''
    status=d.get('outcome') or d.get('outcome_type') or 'unknown'; court=d.get('court') or d.get('court_level') or ''
    verification=d.get('verification_state') or 'review'; source=d.get('source_url') or ''
    for name in names_from_judgment_title(title):
     if record_mention(c,name=name,source_entity_type='judgment',source_entity_id=jid,
      role='party',legal_status=status,source_url=source,event_date=d.get('decision_date') or '',court=court,
      verification_state=verification,confidence=0.7,raw_context=d.get('summary') or title): count+=1
    flags=' '.join(str(d.get('publication_flags') or '').casefold().split())
    restricted=any(token in flags for token in ('publication ban','anonym','initials only','restricted','sealed'))
    raw=' '.join(str(d.get(k) or '') for k in ('summary','decision_text','raw_metadata'))
    file_values=[]
    if d.get('court_file_number'): file_values.append(str(d.get('court_file_number')))
    file_values.extend(re.findall(r'\b(?:file|docket|registry)\s*(?:no\.?|number|#)?\s*[:.-]?\s*([A-Z0-9-]{5,30})',raw,re.I))
    linked=[]; seen_links=set()
    cit=' '.join(str(d.get('citation') or '').casefold().split())
    for item in citation_people.get(cit,[]):
     key=(item.get('person_id'),item.get('display_name'))
     if key not in seen_links: seen_links.add(key); linked.append((item,'citation'))
    for value in file_values:
     fil=re.sub(r'[^a-z0-9]','',value.casefold())
     for item in file_people.get(fil,[]):
      key=(item.get('person_id'),item.get('display_name'))
      if key not in seen_links: seen_links.add(key); linked.append((item,'court file'))
    # Respect publication restrictions: do not reveal a full name when the judgment is anonymized.
    if not restricted:
     for item,method in linked:
      linked_status=item.get('final_outcome') or item.get('legal_status') or status
      linked_ver='verified' if method in ('citation','court file') and item.get('verification_state')=='verified' else 'review'
      conf=.96 if linked_ver=='verified' else .82
      if record_mention(c,name=item.get('display_name'),person_id=item.get('person_id'),source_entity_type='judgment_enriched',source_entity_id=jid,
       role=item.get('role') or 'party',legal_status=linked_status,source_url=source,event_date=d.get('decision_date') or '',
       court_file_number=item.get('court_file_number') or (file_values[0] if file_values else ''),court=court or item.get('court_level') or '',
       location=str(item.get('courthouse_slug') or '').replace('-',' ').title(),offence_text=item.get('offences') or '',
       verification_state=linked_ver,confidence=conf,raw_context=f'Full name linked to judgment by exact {method}: {title}'):
       count+=1
     # Body names are searchable but remain review-only unless corroborated above.
     linked_norms={normalize_name(item.get('display_name')) for item,_ in linked}
     for candidate in extract_person_candidates(raw):
      if normalize_name(candidate['name']) in linked_norms: continue
      if record_mention(c,name=candidate['name'],source_entity_type='judgment_body',source_entity_id=jid,
       role=candidate['role'],legal_status=candidate['legal_status'] if candidate['legal_status']!='unknown' else status,
       source_url=source,event_date=d.get('decision_date') or '',court_file_number=file_values[0] if file_values else '',court=court,
       verification_state='review',confidence=.58,raw_context=candidate['context']): count+=1
 c.commit()
 rebuild_aliases_and_reviews(c)
 return count

PERSON_PATTERNS = [
 (re.compile(r"\b(?:accused|defendant|offender|appellant|respondent|applicant|complainant|victim|witness|counsel|lawyer|judge|justice)\s*[:,-]?\s+([A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){1,4})"), None),
 (re.compile(r"\b([A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){1,4})\s+(?:was|were|is|has been)\s+(charged|convicted|acquitted|sentenced|arrested)\b", re.I), 'subject'),
 (re.compile(r"\bcharged\s+(?:against|with)?\s*([A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){1,4})"), 'accused'),
]

def extract_person_candidates(text):
 """Conservatively extract source-backed person candidates from prose."""
 text=' '.join(str(text or '').replace('\u00ad','').split())
 found=[]
 for pattern, fixed_role in PERSON_PATTERNS:
  for match in pattern.finditer(text):
   name=match.group(1).strip(' ,.;:-')
   before=text[max(0,match.start()-35):match.start()].casefold()
   role=fixed_role or next((r for token,r in ROLE_ALIASES.items() if token in before), 'unknown')
   status='unknown'
   whole=match.group(0).casefold()
   for token,mapped in {'charged':'charged','convicted':'convicted','acquitted':'acquitted','sentenced':'convicted','arrested':'alleged'}.items():
    if token in whole: status=mapped; break
   if plausible_name(name): found.append({'name':display_name(name),'role':role,'legal_status':status,'context':match.group(0)})
 # preserve order, remove duplicate normalized names within one document
 out=[]; seen=set()
 for item in found:
  key=(normalize_name(item['name']),item['role'],item['legal_status'])
  if key not in seen: seen.add(key); out.append(item)
 return out

def ensure_alias_schema(c):
 # Older installs used alias_text/source_document_id/verified and a two-column
 # uniqueness rule. Upgrade that table in place so existing databases remain usable.
 c.executescript('''
 CREATE TABLE IF NOT EXISTS person_aliases(
  alias_id TEXT PRIMARY KEY, person_id TEXT NOT NULL, alias_text TEXT NOT NULL,
  normalized_alias TEXT NOT NULL, alias_type TEXT DEFAULT 'source_variant',
  source_document_id TEXT, verified INTEGER DEFAULT 0, created_at TEXT,
  UNIQUE(person_id,normalized_alias)
 );
 ''')
 cols={r[1] for r in c.execute('PRAGMA table_info(person_aliases)')}
 additions={
  'alias_name':'TEXT', 'source_entity_type':'TEXT', 'source_entity_id':'TEXT',
  'verification_state':"TEXT DEFAULT 'review'", 'confidence':'REAL DEFAULT 0.5',
  'updated_at':'TEXT'
 }
 for name,spec in additions.items():
  if name not in cols:
   c.execute(f'ALTER TABLE person_aliases ADD COLUMN {name} {spec}')
 c.execute("UPDATE person_aliases SET alias_name=COALESCE(NULLIF(alias_name,''),alias_text)")
 c.execute("UPDATE person_aliases SET alias_text=COALESCE(NULLIF(alias_text,''),alias_name)")
 c.execute("UPDATE person_aliases SET verification_state=CASE WHEN verified=1 THEN 'verified' ELSE COALESCE(NULLIF(verification_state,''),'review') END")
 c.execute('CREATE INDEX IF NOT EXISTS idx_person_alias_name ON person_aliases(normalized_alias)')

def record_alias(c, person_id, alias_name, source_entity_type='', source_entity_id='', alias_type='source_variant', verification_state='review', confidence=0.5):
 alias=display_name(alias_name); norm=normalize_name(alias)
 if not plausible_name(alias): return None
 aid=hashlib.sha256(f'{person_id}|{norm}'.encode()).hexdigest()[:40]; stamp=now()
 verified=1 if verification_state=='verified' else 0
 c.execute('''INSERT INTO person_aliases(alias_id,person_id,alias_text,alias_name,normalized_alias,alias_type,source_document_id,source_entity_type,source_entity_id,verified,verification_state,confidence,created_at,updated_at)
 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(person_id,normalized_alias) DO UPDATE SET
 alias_text=excluded.alias_text,alias_name=excluded.alias_name,alias_type=excluded.alias_type,
 source_document_id=COALESCE(excluded.source_document_id,person_aliases.source_document_id),
 source_entity_type=COALESCE(excluded.source_entity_type,person_aliases.source_entity_type),
 source_entity_id=COALESCE(excluded.source_entity_id,person_aliases.source_entity_id),
 verified=MAX(person_aliases.verified,excluded.verified),
 verification_state=CASE WHEN person_aliases.verification_state='verified' THEN 'verified' ELSE excluded.verification_state END,
 confidence=MAX(COALESCE(person_aliases.confidence,0),excluded.confidence),updated_at=excluded.updated_at''',
 (aid,person_id,alias,alias,norm,alias_type,source_entity_id or None,source_entity_type or None,source_entity_id or None,verified,verification_state,float(confidence),stamp,stamp))
 return aid

def _harvest_text_table(c, table, id_col, text_cols, *, source_type, title_col=None, url_col=None, date_col=None, status='unknown', role='unknown', confidence=.52):
 cols={r[1] for r in c.execute(f'PRAGMA table_info({table})')}
 use=[x for x in [id_col,title_col,url_col,date_col,*text_cols] if x and x in cols]
 if id_col not in use or not any(x in cols for x in text_cols): return 0
 count=0
 for row in c.execute(f"SELECT {','.join(dict.fromkeys(use))} FROM {table}"):
  d=dict(row); body='\n'.join(str(d.get(x) or '') for x in text_cols if x in d)
  for item in extract_person_candidates(body):
   mention=record_mention(c,name=item['name'],source_entity_type=source_type,source_entity_id=d.get(id_col),role=item['role'] if item['role']!='unknown' else role,
    legal_status=item['legal_status'] if item['legal_status']!='unknown' else status,source_url=d.get(url_col) if url_col else '',event_date=d.get(date_col) if date_col else '',
    verification_state='review',confidence=confidence,raw_context=item['context'])
   if mention: count+=1
 return count

def rebuild_aliases_and_reviews(c):
 ensure_alias_schema(c)
 tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 # Collapse duplicate mention variants before upserting aliases. This avoids thousands of
 # identical ON CONFLICT updates after a large daily-court import.
 rows=c.execute('''SELECT person_id,normalized_name,MAX(exact_name) exact_name,
  MAX(source_entity_type) source_entity_type,MAX(source_entity_id) source_entity_id,
  CASE WHEN MAX(CASE WHEN verification_state='verified' THEN 1 ELSE 0 END)=1 THEN 'verified' ELSE 'review' END verification_state,
  MAX(COALESCE(confidence,0.5)) confidence
  FROM person_mentions WHERE person_id IS NOT NULL AND normalized_name<>''
  GROUP BY person_id,normalized_name''').fetchall()
 for r in rows:
  record_alias(c,r['person_id'],r['exact_name'],r['source_entity_type'],r['source_entity_id'],'source_variant',r['verification_state'],r['confidence'])
 if 'review_queue' in tables:
  for r in c.execute("SELECT mention_id,exact_name,normalized_name,confidence,raw_context FROM person_mentions WHERE confidence<0.65 OR role='unknown'"):
   reason='Name extraction needs review' if r['confidence']<0.65 else 'Person role needs review'
   rid=hashlib.sha256(f"person_mention|{r['mention_id']}|{reason}".encode()).hexdigest()[:40]
   c.execute("INSERT OR IGNORE INTO review_queue(review_id,entity_type,entity_id,reason,severity,status,created_at) VALUES(?,?,?,?,?,'open',?)",
    (rid,'person_mention',r['mention_id'],reason,'medium',now()))

def collection_metrics(c):
 ensure_schema(c); ensure_alias_schema(c)
 rows=c.execute('''SELECT source_entity_type,COUNT(*) mentions,COUNT(DISTINCT normalized_name) names,
 SUM(CASE WHEN role='unknown' THEN 1 ELSE 0 END) unknown_roles,
 SUM(CASE WHEN confidence<0.65 THEN 1 ELSE 0 END) needs_review
 FROM person_mentions GROUP BY source_entity_type ORDER BY mentions DESC''').fetchall()
 return {'totalMentions':c.execute('SELECT COUNT(*) FROM person_mentions').fetchone()[0],
  'distinctNames':c.execute('SELECT COUNT(DISTINCT normalized_name) FROM person_mentions').fetchone()[0],
  'people':c.execute('SELECT COUNT(*) FROM people').fetchone()[0],
  'aliases':c.execute('SELECT COUNT(*) FROM person_aliases').fetchone()[0],
  'sources':[dict(r) for r in rows]}
