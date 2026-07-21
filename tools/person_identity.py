#!/usr/bin/env python3
from __future__ import annotations
import json,re,sqlite3,uuid,unicodedata
try:
 from disposition_parser import run as parse_dispositions
except ModuleNotFoundError:
 import importlib.util as _ilu
 _spec=_ilu.spec_from_file_location('disposition_parser',__import__('pathlib').Path(__file__).with_name('disposition_parser.py'))
 _mod=_ilu.module_from_spec(_spec); _spec.loader.exec_module(_mod); parse_dispositions=_mod.run
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'database'/'bc_justice.db'; DATA=ROOT/'data'
def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def norm(v):
 text=unicodedata.normalize('NFKD',str(v or '')).encode('ascii','ignore').decode().casefold()
 return ' '.join(re.sub(r'[^a-z0-9]+',' ',text).split())
def clean_name(v): return ' '.join(str(v or '').replace('’',"'").split()).strip(' ,;')
def name_parts(v):
 text=clean_name(v).replace(',',' '); bits=[x for x in re.split(r'\s+',text) if x]
 return bits
def expanded_name_variants(v):
 name=clean_name(v); bits=name_parts(name); out={name}
 if not bits:return []
 # surname-first source forms and ordinary first-last forms
 if ',' in name:
  left,right=[clean_name(x) for x in name.split(',',1)]; rb=name_parts(right)
  if rb: out.add(' '.join(rb+[left])); bits=rb+[left]
 first,last=bits[0],bits[-1]
 out.update({f'{last}, {" ".join(bits[:-1])}',f'{" ".join(bits[:-1])} {last}',f'{first} {last}',f'{first[0]}. {last}',f'{first[0]} {last}'})
 if len(bits)>2:
  middle=bits[1:-1]; out.add(f'{first} {middle[0][0]}. {last}'); out.add(f'{first} {" ".join(middle)} {last}')
 # punctuation/spacing variants, without treating nicknames as verified aliases
 for x in list(out):
  out.add(x.replace("'",'')); out.add(x.replace('-',' ')); out.add(x.replace('.',''))
 return sorted({clean_name(x) for x in out if norm(x)})
def uid(*p): return str(uuid.uuid5(uuid.NAMESPACE_URL,'|'.join(map(str,p))))
def soundex(value):
 text=''.join(ch for ch in norm(value) if ch.isalpha())
 if not text:return ''
 first=text[0].upper(); mapping={'b':'1','f':'1','p':'1','v':'1','c':'2','g':'2','j':'2','k':'2','q':'2','s':'2','x':'2','z':'2','d':'3','t':'3','l':'4','m':'5','n':'5','r':'6'}
 digits=[]; previous=mapping.get(text[0],'')
 for ch in text[1:]:
  code=mapping.get(ch,'')
  if code and code!=previous: digits.append(code)
  previous=code
 return (first+''.join(digits)+'000')[:4]
def levenshtein(a,b,max_distance=3):
 a,b=norm(a),norm(b)
 if abs(len(a)-len(b))>max_distance:return max_distance+1
 prev=list(range(len(b)+1))
 for i,ca in enumerate(a,1):
  cur=[i]
  for j,cb in enumerate(b,1):cur.append(min(cur[-1]+1,prev[j]+1,prev[j-1]+(ca!=cb)))
  if min(cur)>max_distance:return max_distance+1
  prev=cur
 return prev[-1]
def name_signature(value):
 bits=name_parts(value)
 return {'first':norm(bits[0]) if bits else '', 'middle':norm(' '.join(bits[1:-1])) if len(bits)>2 else '', 'last':norm(bits[-1]) if len(bits)>1 else '', 'phonetic_first':soundex(bits[0]) if bits else '', 'phonetic_last':soundex(bits[-1]) if len(bits)>1 else ''}
def signal_values(c,pid,typ):
 return {norm(r['signal_value']) for r in c.execute('SELECT signal_value FROM person_identity_signals WHERE person_id=? AND signal_type=?',(pid,typ)) if norm(r['signal_value'])}
def dated_ages(c,pid):
 rows=[]
 if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='published_judgments'").fetchone(): return rows
 cols={r[1] for r in c.execute('PRAGMA table_info(published_judgments)')}
 if 'judgment_id' not in cols or 'decision_date' not in cols:return rows
 for r in c.execute("SELECT s.signal_value,j.decision_date FROM person_identity_signals s JOIN published_judgments j ON j.judgment_id=s.source_entity_id WHERE s.person_id=? AND s.signal_type='published_age'",(pid,)):
  try:
   year=int(str(r['decision_date'])[:4]); age=int(str(r['signal_value']).strip())
   if 0<=age<=120 and 1800<=year<=2200: rows.append((year,age))
  except (ValueError,TypeError):pass
 return rows

def age_conflicts(c,a,b):
 conflicts=[]
 years_a=signal_values(c,a,'birth_year')|signal_values(c,a,'published_birth_year'); years_b=signal_values(c,b,'birth_year')|signal_values(c,b,'published_birth_year')
 if years_a and years_b and years_a.isdisjoint(years_b): conflicts.append('conflicting birth year')
 ages_a=signal_values(c,a,'published_age'); ages_b=signal_values(c,b,'published_age')
 if ages_a and ages_b:
  try:
   if min(abs(int(x)-int(y)) for x in ages_a for y in ages_b)>8: conflicts.append('conflicting published age')
  except ValueError:pass
 timeline=dated_ages(c,a)+dated_ages(c,b)
 for i,(year_a,age_a) in enumerate(timeline):
  for year_b,age_b in timeline[i+1:]:
   expected=age_a+(year_b-year_a)
   if abs(expected-age_b)>2: conflicts.append(f'impossible age timeline ({age_a} in {year_a}; {age_b} in {year_b})')
 return sorted(set(conflicts))

def shared_signal_values(c,a,b,types):
 out=[]
 for typ in types:
  va=signal_values(c,a,typ); vb=signal_values(c,b,typ); shared=sorted(va&vb)
  if shared: out.append((typ,shared))
 return out
SCHEMA='''
CREATE TABLE IF NOT EXISTS identity_candidates(candidate_id TEXT PRIMARY KEY,person_a TEXT,person_b TEXT,match_score REAL,reasons TEXT,status TEXT DEFAULT 'open',created_at TEXT);
CREATE TABLE IF NOT EXISTS person_aliases(alias_id TEXT PRIMARY KEY,person_id TEXT NOT NULL,alias_text TEXT NOT NULL,normalized_alias TEXT NOT NULL,alias_type TEXT DEFAULT 'published',source_document_id TEXT,verified INTEGER DEFAULT 0,created_at TEXT,UNIQUE(person_id,normalized_alias));
CREATE TABLE IF NOT EXISTS person_identity_signals(signal_id TEXT PRIMARY KEY,person_id TEXT NOT NULL,signal_type TEXT NOT NULL,signal_value TEXT NOT NULL,source_entity_type TEXT,source_entity_id TEXT,confidence REAL DEFAULT 0.5,verified INTEGER DEFAULT 0,created_at TEXT);
CREATE TABLE IF NOT EXISTS person_identity_decisions(decision_id TEXT PRIMARY KEY,pair_key TEXT,person_a TEXT,person_b TEXT,decision TEXT NOT NULL,notes TEXT,reviewer TEXT,source TEXT,active INTEGER DEFAULT 1,decided_at TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS offence_dictionary(offence_key TEXT PRIMARY KEY,act_name TEXT,section_text TEXT,canonical_offence TEXT,offence_group TEXT,aliases TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS conviction_events(event_id TEXT PRIMARY KEY,person_id TEXT NOT NULL,case_id TEXT NOT NULL,event_date TEXT,event_key TEXT,offence_groups TEXT,convicted_charge_count INTEGER DEFAULT 0,source_type TEXT,verified INTEGER DEFAULT 0,created_at TEXT,offence_date TEXT,conviction_date TEXT,linked_case_ids TEXT,proceeding_types TEXT,source_quality TEXT,UNIQUE(person_id,case_id,event_key));
CREATE TABLE IF NOT EXISTS linked_proceedings(link_id TEXT PRIMARY KEY,person_id TEXT,underlying_event_key TEXT,case_id TEXT,related_case_id TEXT,relationship_type TEXT,match_reason TEXT,confidence REAL DEFAULT 0.5,created_at TEXT);
CREATE TABLE IF NOT EXISTS judgment_prior_history(history_id TEXT PRIMARY KEY,judgment_id TEXT,person_id TEXT,description TEXT,total_prior_convictions INTEGER,first_known_year TEXT,last_known_year TEXT,offence_groups TEXT,independently_verified INTEGER DEFAULT 0,confidence REAL DEFAULT 0.5,created_at TEXT);
'''
GROUPS=[
 ('criminal code','violence',['assault','homicide','murder','robbery','threat','harass']),('criminal code','sexual offences',['sexual','indecent']),('criminal code','property',['theft','break and enter','mischief','possession of stolen']),('criminal code','fraud and financial',['fraud','forgery','launder']),('criminal code','weapons and firearms',['firearm','weapon','gun']),('controlled drugs and substances act','drug offences',['drug','cocaine','fentanyl','methamphetamine','trafficking']),('motor vehicle act','driving and traffic',['impaired','driving','motor vehicle','traffic']),('criminal code','administration of justice',['breach','failure to comply','obstruct','escape']),('criminal code','public order',['disturbance','riot','public peace']),('environmental','environmental and regulatory',['environment','wildlife','fisheries','workplace','regulatory'])]
def classify(offence,statute=''):
 text=norm(f'{statute} {offence}')
 for act,group,words in GROUPS:
  if any(w in text for w in words): return act.title() if act!='environmental' else (statute or 'Regulatory law'),group
 return statute or 'Other legislation','other offences'
def setup(c):
 c.executescript(SCHEMA)
 cols={r[1] for r in c.execute('PRAGMA table_info(people)')}
 for spec in ['birth_year TEXT','sex TEXT','identity_status TEXT DEFAULT \'unreviewed\'','identity_notes TEXT']:
  if spec.split()[0] not in cols: c.execute(f'ALTER TABLE people ADD COLUMN {spec}')
 cols={r[1] for r in c.execute('PRAGMA table_info(charges)')}
 for spec in ['canonical_offence TEXT','offence_group TEXT','event_key TEXT']:
  if spec.split()[0] not in cols: c.execute(f'ALTER TABLE charges ADD COLUMN {spec}')
 ecols={r[1] for r in c.execute('PRAGMA table_info(conviction_events)')}
 for spec in ['offence_date TEXT','conviction_date TEXT','linked_case_ids TEXT','proceeding_types TEXT','source_quality TEXT']:
  if spec.split()[0] not in ecols: c.execute(f'ALTER TABLE conviction_events ADD COLUMN {spec}')
 # Migrate older identity-decision tables without losing review history.
 dcols={r[1] for r in c.execute('PRAGMA table_info(person_identity_decisions)')}
 for spec in ['pair_key TEXT','reviewer TEXT','source TEXT','active INTEGER DEFAULT 1','updated_at TEXT']:
  if spec.split()[0] not in dcols: c.execute(f'ALTER TABLE person_identity_decisions ADD COLUMN {spec}')
 for row in c.execute('SELECT decision_id,person_a,person_b,decided_at FROM person_identity_decisions').fetchall():
  if row['person_a'] and row['person_b']:
   pair='|'.join(sorted((str(row['person_a']),str(row['person_b']))))
   c.execute('UPDATE person_identity_decisions SET pair_key=COALESCE(pair_key,?),active=COALESCE(active,1),updated_at=COALESCE(updated_at,decided_at,?) WHERE decision_id=?',(pair,now(),row['decision_id']))
 c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_identity_decision_pair ON person_identity_decisions(pair_key) WHERE active=1')
 c.commit()
def aliases(c):
 n=0
 for p in c.execute('SELECT person_id,display_name,normalized_name FROM people').fetchall():
  vals=set(expanded_name_variants(p['display_name']))
  if p['normalized_name']: vals.add(p['normalized_name'])
  for v in vals:
   if not norm(v): continue
   alias_type='published' if clean_name(v)==clean_name(p['display_name']) else 'generated-format'
   verified=1 if alias_type=='published' else 0
   before=c.total_changes
   stamp=now()
   c.execute('''INSERT OR IGNORE INTO person_aliases
    (alias_id,person_id,alias_text,normalized_alias,alias_type,source_document_id,verified,created_at)
    VALUES(?,?,?,?,?,?,?,?)''',
    (uid('alias',p['person_id'],norm(v)),p['person_id'],v,norm(v),alias_type,None,verified,stamp))
   alias_cols={r[1] for r in c.execute('PRAGMA table_info(person_aliases)')}
   updates=[]; values=[]
   if 'alias_name' in alias_cols: updates.append("alias_name=COALESCE(NULLIF(alias_name,''),?)"); values.append(v)
   if 'verification_state' in alias_cols: updates.append("verification_state=CASE WHEN verified=1 THEN 'verified' ELSE COALESCE(NULLIF(verification_state,''),'review') END")
   if 'confidence' in alias_cols: updates.append('confidence=MAX(COALESCE(confidence,0),?)'); values.append(1.0 if verified else 0.55)
   if 'updated_at' in alias_cols: updates.append('updated_at=?'); values.append(stamp)
   if updates:
    values.extend([p['person_id'],norm(v)])
    c.execute(f"UPDATE person_aliases SET {','.join(updates)} WHERE person_id=? AND normalized_alias=?",values)
   n+=c.total_changes-before
 return n

def normalize_offences(c):
 n=0
 for r in c.execute('SELECT charge_id,offence_text,statute,section FROM charges').fetchall():
  act,group=classify(r['offence_text'],r['statute']); canonical=' '.join(str(r['offence_text'] or '').split()) or group.title(); key=norm(f'{act} {r["section"]} {canonical}')
  c.execute('UPDATE charges SET canonical_offence=?,offence_group=? WHERE charge_id=?',(canonical,group,r['charge_id']))
  c.execute('INSERT OR REPLACE INTO offence_dictionary VALUES(?,?,?,?,?,?,?)',(key,act,r['section'],canonical,group,'[]',now())); n+=1
 return n
def confidence(c):
 people={r['person_id']:dict(r) for r in c.execute('SELECT * FROM people')}
 judgment_rows=[]
 if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='published_judgments'").fetchone():
  cols={r[1] for r in c.execute('PRAGMA table_info(published_judgments)')}
  use=[x for x in ('judgment_id','case_title','case_name','title','decision_text','summary','raw_metadata','court','court_level','decision_date') if x in cols]
  if use: judgment_rows=[dict(x) for x in c.execute(f"SELECT {','.join(use)} FROM published_judgments")]
 for pid,p in people.items():
  # Rebuild generated signals, retaining manual/published verified evidence.
  c.execute("DELETE FROM person_identity_signals WHERE person_id=? AND verified=0",(pid,))
  signals=[]
  cases=[dict(r) for r in c.execute('SELECT c.* FROM cases c JOIN case_people cp ON cp.case_id=c.case_id WHERE cp.person_id=?',(pid,)).fetchall()]
  courts={str(r.get('courthouse_slug') or '') for r in cases if r.get('courthouse_slug')}; citations={str(r.get('citation') or '') for r in cases if r.get('citation')}
  locations={x.replace('-',' ').title() for x in courts if x}
  bits=name_parts(p.get('display_name'))
  if len(bits)>2:
   signals.append(('middle_name',' '.join(bits[1:-1]),.16,0,'person',pid))
   signals.append(('middle_initials',' '.join(x[0].upper() for x in bits[1:-1] if x),.08,0,'person',pid))
  if citations: signals.append(('linked_citations',str(len(citations)),min(.22,.08*len(citations)),0,'person',pid))
  if len(courts)==1 and courts: signals.append(('consistent_courthouse',next(iter(courts)),.12,0,'person',pid))
  for loc in sorted(locations)[:5]: signals.append(('case_location',loc,.08,0,'person',pid))
  if p.get('date_of_birth'): signals.append(('date_of_birth',p['date_of_birth'],.45,1,'person',pid))
  if p.get('birth_year'): signals.append(('birth_year',p['birth_year'],.25,1,'person',pid))
  if p.get('sex'): signals.append(('published_sex',p['sex'],.08,1,'person',pid))
  # Extract only explicitly published identity clues from judgments whose title contains the full normalized name.
  pname=norm(p.get('display_name'))
  for j in judgment_rows:
   title=' '.join(str(j.get(k) or '') for k in ('case_title','case_name','title'))
   if not pname or pname not in norm(title): continue
   text=' '.join(str(j.get(k) or '') for k in ('decision_text','summary','raw_metadata'))
   jid=str(j.get('judgment_id') or '')
   age=re.search(r'\b(?:aged?|age)\s+(\d{1,3})\b',text,re.I)
   if age: signals.append(('published_age',age.group(1),.14,0,'judgment',jid))
   born=re.search(r'\b(?:born|date of birth|dob)\s*(?:in|:)?\s*((?:19|20)\d{2})\b',text,re.I)
   if born: signals.append(('published_birth_year',born.group(1),.24,0,'judgment',jid))
   residence=re.search(r"\b(?:resident of|resides in|from)\s+([A-Z][A-Za-z .'-]{2,40})(?=[,.;])",text)
   if residence: signals.append(('published_residence',clean_name(residence.group(1)),.10,0,'judgment',jid))
   counsel=re.findall(r"\b(?:counsel|lawyer)\s+(?:for\s+(?:the\s+)?(?:accused|defendant|appellant))?\s*[:,-]?\s*([A-Z][A-Za-z .'-]{3,60})",text,re.I)
   for val in counsel[:2]: signals.append(('counsel_reference',clean_name(val),.04,0,'judgment',jid))
   coacc=re.findall(r"\bco[- ]accused\s+([A-Z][A-Za-z .'-]{3,60})",text,re.I)
   for val in coacc[:3]: signals.append(('co_accused_reference',clean_name(val),.05,0,'judgment',jid))
   if re.search(r'\b(?:same offender|same accused|previously before (?:this|the) court)\b',text,re.I): signals.append(('explicit_same_offender_reference','yes',.28,0,'judgment',jid))
  unique={}
  for typ,val,sc,ver,setype,seid in signals:
   if norm(val): unique[(typ,norm(val),setype,seid)]=(typ,str(val),sc,ver,setype,seid)
  # Base confidence remains cautious; corroborating evidence helps, but generated formatting aliases do not.
  score=min(.99,.30+sum(x[2] for x in unique.values()))
  status='verified' if score>=.85 else 'likely' if score>=.65 else 'possible'
  c.execute('UPDATE people SET identity_confidence=?,identity_status=?,updated_at=? WHERE person_id=?',(score,status,now(),pid))
  for typ,val,sc,ver,setype,seid in unique.values():
   c.execute('INSERT OR REPLACE INTO person_identity_signals VALUES(?,?,?,?,?,?,?,?,?)',(uid('signal',pid,typ,val,setype,seid),pid,typ,val,setype,seid,sc,ver,now()))

def build_identity_candidates(c):
 c.execute("DELETE FROM identity_candidates WHERE status='open'")
 people=[dict(r) for r in c.execute('SELECT person_id,display_name,normalized_name,birth_year,identity_confidence FROM people ORDER BY display_name')]
 # Prefetch identity signals once. The old implementation queried SQLite several times
 # for every possible person pair, which becomes effectively unbounded after court-list imports.
 signal_cache={}
 for r in c.execute('SELECT person_id,signal_type,signal_value FROM person_identity_signals'):
  value=norm(r['signal_value'])
  if value: signal_cache.setdefault((r['person_id'],r['signal_type']),set()).add(value)
 dated_cache={}
 if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='published_judgments'").fetchone():
  cols={r[1] for r in c.execute('PRAGMA table_info(published_judgments)')}
  if {'judgment_id','decision_date'} <= cols:
   for r in c.execute("SELECT s.person_id,s.signal_value,j.decision_date FROM person_identity_signals s JOIN published_judgments j ON j.judgment_id=s.source_entity_id WHERE s.signal_type='published_age'"):
    try:
     year=int(str(r['decision_date'])[:4]); age=int(str(r['signal_value']).strip())
     if 0<=age<=120 and 1800<=year<=2200: dated_cache.setdefault(r['person_id'],[]).append((year,age))
    except (ValueError,TypeError): pass
 def values(pid,typ): return signal_cache.get((pid,typ),set())
 def conflicts_for(a,b):
  conflicts=[]
  years_a=values(a,'birth_year')|values(a,'published_birth_year'); years_b=values(b,'birth_year')|values(b,'published_birth_year')
  if years_a and years_b and years_a.isdisjoint(years_b): conflicts.append('conflicting birth year')
  ages_a=values(a,'published_age'); ages_b=values(b,'published_age')
  if ages_a and ages_b:
   try:
    if min(abs(int(x)-int(y)) for x in ages_a for y in ages_b)>8: conflicts.append('conflicting published age')
   except ValueError: pass
  timeline=dated_cache.get(a,[])+dated_cache.get(b,[])
  for i,(year_a,age_a) in enumerate(timeline):
   for year_b,age_b in timeline[i+1:]:
    if abs((age_a+(year_b-year_a))-age_b)>2: conflicts.append(f'impossible age timeline ({age_a} in {year_a}; {age_b} in {year_b})')
  return sorted(set(conflicts))
 def shared(a,b,types):
  out=[]
  for typ in types:
   vals=values(a,typ)&values(b,typ)
   if vals: out.append((typ,sorted(vals)))
  return out
 last_counts={}; blocks={}
 for p in people:
  sig=name_signature(p['display_name']); p['_sig']=sig
  last_counts[sig['last']]=last_counts.get(sig['last'],0)+1
  # Compare only people with an exact, phonetic, or near surname candidate. This changes
  # the work from all-pairs O(n²) to small surname blocks while preserving prior rules.
  keys={('exact',sig['last']),('phonetic',sig['phonetic_last'])}
  for key in keys:
   if key[1]: blocks.setdefault(key,[]).append(p)
 decisions={(min(str(r['person_a']),str(r['person_b'])),max(str(r['person_a']),str(r['person_b']))):r['decision'] for r in c.execute('SELECT person_a,person_b,decision FROM person_identity_decisions WHERE COALESCE(active,1)=1') if r['person_a'] and r['person_b']}
 pairs={}
 # Large daily-court imports can create thousands of one-source people. Do not generate
 # every same-surname pair: require compatible given-name evidence before adding a pair,
 # and skip very large phonetic-only blocks which otherwise dominate runtime.
 for (block_type,_),group in blocks.items():
  if block_type=='phonetic' and len(group)>80:
   continue
  by_initial={}
  for person in group:
   sig=person['_sig']; initial=(sig['first'][:1] if sig['first'] else '')
   by_initial.setdefault(initial,[]).append(person)
  for initial,subset in by_initial.items():
   if not initial or len(subset)>250:
    continue
   for i,a in enumerate(subset):
    for b in subset[i+1:]:
     sa=a['_sig']; sb=b['_sig']
     # Exact/similar first names, matching middle evidence, or a shared strong signal
     # is required before the more expensive conflict/scoring pass.
     given_ok=(sa['first']==sb['first'] or
               (sa['phonetic_first'] and sa['phonetic_first']==sb['phonetic_first']) or
               levenshtein(sa['first'],sb['first'],2)<=2)
     middle_ok=bool(sa['middle'] and sb['middle'] and sa['middle'][0]==sb['middle'][0])
     strong_shared=bool(shared(a['person_id'],b['person_id'],('court_file_number','citation','explicit_same_offender_reference')))
     if not (given_ok or middle_ok or strong_shared):
      continue
     pairs[(min(a['person_id'],b['person_id']),max(a['person_id'],b['person_id']))]=(a,b)
 n=0
 for pair,(a,b) in pairs.items():
  if pair in decisions: continue
  sa=a['_sig']; sb=b['_sig']; reasons=[]; conflicts=conflicts_for(a['person_id'],b['person_id']); score=0.0
  if sa['last'] and sa['last']==sb['last']:score+=.34;reasons.append('exact surname')
  elif sa['phonetic_last'] and sa['phonetic_last']==sb['phonetic_last']:score+=.22;reasons.append('phonetic surname')
  elif sa['last'] and sb['last'] and levenshtein(sa['last'],sb['last'],2)<=2:score+=.16;reasons.append('similar surname spelling')
  else:continue
  if sa['first']==sb['first']:score+=.30;reasons.append('exact given name')
  elif sa['phonetic_first'] and sa['phonetic_first']==sb['phonetic_first']:score+=.18;reasons.append('phonetic given name')
  elif sa['first'] and sb['first'] and (sa['first'][0]==sb['first'][0] or levenshtein(sa['first'],sb['first'],2)<=2):score+=.10;reasons.append('initial or similar given name')
  if sa['middle'] and sb['middle']:
   if sa['middle']==sb['middle']:score+=.20;reasons.append('matching middle name')
   elif sa['middle'][0]!=sb['middle'][0]:conflicts.append('conflicting middle initial')
   elif levenshtein(sa['middle'],sb['middle'],1)>1:conflicts.append('conflicting middle name')
  elif bool(sa['middle']) != bool(sb['middle']):reasons.append('middle name unavailable on one record')
  for typ,vals in shared(a['person_id'],b['person_id'],('case_location','consistent_courthouse')):
   score+=.12 if typ=='consistent_courthouse' else .08
   reasons.append(('shared courthouse' if typ=='consistent_courthouse' else 'shared location')+f' ({vals[0]})')
  common=max(last_counts.get(sa['last'],1),1)
  if common>=5:score-=.20;reasons.append(f'common surname ({common} records)')
  elif common>=3:score-=.10;reasons.append(f'repeated surname ({common} records)')
  if conflicts:score-=.45*len(conflicts)
  score=max(0,min(.99,score))
  if score<.40:continue
  reason_text='; '.join(reasons + [f'conflict: {x}' for x in conflicts])
  cid=uid('identity-candidate',*pair)
  c.execute('INSERT OR REPLACE INTO identity_candidates(candidate_id,person_a,person_b,match_score,reasons,status,created_at) VALUES(?,?,?,?,?,?,?)',(cid,a['person_id'],b['person_id'],score,reason_text,'open',now()));n+=1
 return n

def events(c):
 c.execute('DELETE FROM conviction_events'); c.execute('DELETE FROM linked_proceedings'); n=0
 case_cols={r[1] for r in c.execute('PRAGMA table_info(cases)')}; charge_cols={r[1] for r in c.execute('PRAGMA table_info(charges)')}; outcome_cols={r[1] for r in c.execute('PRAGMA table_info(outcomes)')}
 def val(row,*names):
  for name in names:
   if name in row.keys() and row[name] not in (None,''): return row[name]
  return None
 def proceeding_type(case):
  text=norm(' '.join(str(val(case,x) or '') for x in ('case_type','case_title','legal_status','final_outcome','source_type','notes')))
  if 'appeal' in text:return 'appeal'
  if 'retrial' in text or 'new trial' in text:return 'retrial'
  if 'sentence' in text:return 'sentencing'
  return 'trial/original'
 def citation_root(value):
  text=norm(value); return re.sub(r'\b(?:appeal|sentencing|sentence|retrial)\b','',text).strip()
 people_cases=c.execute('''SELECT p.person_id,c.* FROM people p JOIN case_people cp ON cp.person_id=p.person_id JOIN cases c ON c.case_id=cp.case_id''').fetchall()
 candidates=[]
 for case in people_cases:
  pid=case['person_id']; case_id=case['case_id']
  outcomes=[dict(x) for x in c.execute('SELECT * FROM outcomes WHERE case_id=?',(case_id,))]
  charges=[dict(x) for x in c.execute('SELECT * FROM charges WHERE case_id=?',(case_id,))]
  verified=case['verification_state']=='verified' or any(bool(x.get('verified')) for x in outcomes)
  outcome=norm(next((val(x,'outcome_type') for x in outcomes if val(x,'outcome_type')),val(case,'final_outcome','legal_status')))
  if not verified or outcome not in ('convicted','guilty','guilty plea'): continue
  offence_dates=[]; event_keys=[]; occurrence_ids=[]; groups=set(); charge_count=0
  for ch in charges:
   disp=norm(val(ch,'disposition') or outcome)
   if disp in ('convicted','guilty','proven','guilty plea') or outcome in ('convicted','guilty','guilty plea'): charge_count+=1
   groups.add(val(ch,'offence_group') or 'other offences')
   d=val(ch,'offence_date','incident_date','occurrence_date','event_date');
   if d: offence_dates.append(str(d))
   k=val(ch,'event_key','occurrence_number','incident_number','occurrence_id');
   if k: event_keys.append(norm(k)); occurrence_ids.append(str(k))
  offence_date=min(offence_dates) if offence_dates else str(val(case,'offence_date','incident_date','opened_date') or '')
  conviction_date=str(next((val(x,'outcome_date') for x in outcomes if val(x,'outcome_date')),val(case,'outcome_date','closed_date')) or '')
  ptype=proceeding_type(case)
  explicit_related=str(val(case,'related_case_id','parent_case_id','original_case_id','appeal_from_case_id') or '')
  citation=str(val(case,'citation') or '')
  court_file=str(val(case,'court_file_number') or '')
  # Prefer incident identifiers and offence dates. Proceeding/citation/file clues only link records; they do not create extra events.
  if event_keys: base='occurrence:'+sorted(set(event_keys))[0]
  elif offence_date: base='date:'+norm(offence_date)
  elif explicit_related: base='related:'+norm(explicit_related)
  elif citation: base='citation:'+citation_root(citation)
  else: base='case:'+norm(case_id)
  candidates.append({'person_id':pid,'case_id':case_id,'base':base,'offence_date':offence_date,'conviction_date':conviction_date,'event_date':conviction_date or offence_date,'groups':groups,'charge_count':max(charge_count,1),'ptype':ptype,'citation':citation,'file':court_file,'related':explicit_related,'occurrences':occurrence_ids})
 # Link appeals/sentencing/retrials and same underlying file/citation to an original event.
 by_person={}
 for x in candidates: by_person.setdefault(x['person_id'],[]).append(x)
 for pid,items in by_person.items():
  for item in items:
   for other in items:
    if item is other:continue
    reason=''; relationship=''
    if item['related'] and item['related']==other['case_id']: reason='explicit related-case field'; relationship=item['ptype']
    elif item['file'] and other['file'] and norm(item['file'])==norm(other['file']): reason='same court file number'; relationship=item['ptype']
    elif item['citation'] and other['citation'] and citation_root(item['citation'])==citation_root(other['citation']): reason='same citation root'; relationship=item['ptype']
    elif item['offence_date'] and other['offence_date'] and item['offence_date']==other['offence_date'] and item['ptype']!='trial/original': reason='same offence date'; relationship=item['ptype']
    if reason:
     original=other if other['ptype']=='trial/original' else item
     item['base']=original['base']
     c.execute('INSERT OR REPLACE INTO linked_proceedings VALUES(?,?,?,?,?,?,?,?,?)',(uid('proceeding-link',pid,item['case_id'],other['case_id']),pid,item['base'],item['case_id'],other['case_id'],relationship or 'related proceeding',reason,.9 if 'explicit' in reason else .75,now()))
     break
 seen={}
 for x in candidates:
  event_key=norm(f"{x['person_id']} {x['base']}")
  item=seen.setdefault(event_key,{'person_id':x['person_id'],'case_id':x['case_id'],'offence_date':x['offence_date'],'conviction_date':x['conviction_date'],'event_date':x['event_date'],'groups':set(),'charge_count':0,'case_ids':set(),'types':set()})
  item['case_ids'].add(x['case_id']); item['types'].add(x['ptype']); item['groups'].update(x['groups']); item['charge_count']+=x['charge_count']
  if x['offence_date'] and (not item['offence_date'] or x['offence_date']<item['offence_date']):item['offence_date']=x['offence_date']
  if x['conviction_date'] and (not item['conviction_date'] or x['conviction_date']>item['conviction_date']):item['conviction_date']=x['conviction_date']
  item['event_date']=item['conviction_date'] or item['offence_date']
 for event_key,item in seen.items():
  linked=sorted(item['case_ids']); source='linked proceedings' if len(linked)>1 else 'case/outcome'; quality='verified court outcome'
  c.execute('''INSERT OR REPLACE INTO conviction_events(event_id,person_id,case_id,event_date,event_key,offence_groups,convicted_charge_count,source_type,verified,created_at,offence_date,conviction_date,linked_case_ids,proceeding_types,source_quality) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(uid('conviction-event',item['person_id'],event_key),item['person_id'],item['case_id'],item['event_date'],event_key,', '.join(sorted(item['groups'])) or 'other offences',item['charge_count'],source,1,now(),item['offence_date'],item['conviction_date'],json.dumps(linked),json.dumps(sorted(item['types'])),quality)); n+=1
 return n

def prior_history(c):
 if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='published_judgments'").fetchone(): return 0
 c.execute('DELETE FROM judgment_prior_history'); n=0
 cols={r[1] for r in c.execute('PRAGMA table_info(published_judgments)')}
 wanted=[x for x in ('judgment_id','case_title','case_name','title','raw_metadata','decision_text','summary','decision_date') if x in cols]
 if not wanted:return 0
 number_words={'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10,'eleven':11,'twelve':12,'thirteen':13,'fourteen':14,'fifteen':15,'sixteen':16,'seventeen':17,'eighteen':18,'nineteen':19,'twenty':20}
 group_words={'violence':['assault','robbery','homicide','violent'],'property':['theft','break and enter','mischief','property'],'driving and traffic':['impaired driving','driving offence','motor vehicle'],'drug offences':['drug','trafficking','possession for the purpose'],'weapons and firearms':['firearm','weapon'],'administration of justice':['breach','failure to comply','probation','recognizance']}
 patterns=[
  re.compile(r'[^\n.]{0,70}(?:prior|previous|criminal)\s+(?:record|history|convictions?)[^\n.]{0,260}',re.I),
  re.compile(r'[^\n.]{0,100}\b(?:convicted|convictions?)\b[^\n.]{0,180}\b(?:before|previously|prior)\b[^\n.]{0,80}',re.I),
  re.compile(r'\b(?:no|without)\s+(?:prior|previous)\s+(?:criminal\s+)?(?:record|convictions?)[^\n.]{0,80}',re.I),
  re.compile(r'\b(?:first|most recent|last)\s+(?:known\s+)?conviction[^\n.]{0,120}',re.I)
 ]
 for row in c.execute(f"SELECT {','.join(wanted)} FROM published_judgments").fetchall():
  r=dict(row); text=' '.join(str(r.get(k) or '') for k in wanted); matches=[]
  for patt in patterns: matches.extend(patt.findall(text))
  matches=list(dict.fromkeys(' '.join(x.split()) for x in matches if x.strip()))
  if not matches: continue
  joined=' '.join(matches)
  no_prior=bool(re.search(r'\b(?:no|without)\s+(?:prior|previous)\s+(?:criminal\s+)?(?:record|convictions?)',joined,re.I))
  nums=[int(x) for x in re.findall(r'\b(\d{1,3})\s+(?:prior|previous)?\s*convictions?\b',joined,re.I)]
  nums += [value for word,value in number_words.items() if re.search(rf'\b{word}\s+(?:prior|previous)?\s*convictions?\b',joined,re.I)]
  total=0 if no_prior else (max(nums) if nums else None)
  years=[int(x) for x in re.findall(r'\b(19\d{2}|20\d{2})\b',joined)]
  groups=[group for group,words in group_words.items() if any(w in norm(joined) for w in words)]
  title=' '.join(str(r.get(k) or '') for k in ('case_title','case_name','title'))
  people=[]
  for part in re.split(r'\s+v\.?\s+',title,flags=re.I):
   part=clean_name(part)
   if part and norm(part) not in ('r','the king','the queen','regina'): people.append(part)
  person_id=None
  for person in people:
   hit=c.execute('SELECT person_id FROM people WHERE normalized_name=?',(norm(person),)).fetchone()
   if hit: person_id=hit['person_id']; break
  confidence=.75 if total is not None else .62
  c.execute('INSERT INTO judgment_prior_history VALUES(?,?,?,?,?,?,?,?,?,?,?)',(uid('prior',r['judgment_id']),r['judgment_id'],person_id,'; '.join(matches)[:4000],total,str(min(years)) if years else None,str(max(years)) if years else None,json.dumps(groups),0,confidence,now())); n+=1
 return n

def export(c):
 profiles=[]
 for p in c.execute('SELECT * FROM people ORDER BY display_name').fetchall():
  pid=p['person_id']
  profile=dict(p); profile['aliases']=[dict(x) for x in c.execute('SELECT alias_text,alias_type,verified FROM person_aliases WHERE person_id=? ORDER BY verified DESC,alias_text',(pid,))]
  profile['signals']=[dict(x) for x in c.execute('SELECT signal_type,signal_value,confidence,verified FROM person_identity_signals WHERE person_id=?',(pid,))]
  profile['cases']=[dict(x) for x in c.execute('''SELECT c.*,cp.role FROM cases c JOIN case_people cp ON cp.case_id=c.case_id WHERE cp.person_id=? ORDER BY COALESCE(c.outcome_date,c.closed_date,c.opened_date) DESC''',(pid,))]
  for case in profile['cases']:
   case['charges']=[dict(x) for x in c.execute('SELECT offence_text,statute,section,canonical_offence,offence_group,disposition FROM charges WHERE case_id=?',(case.get('case_id'),))]
   case['outcomes']=[dict(x) for x in c.execute('SELECT outcome_type,outcome_date,sentence_summary,verified FROM outcomes WHERE case_id=? ORDER BY outcome_date DESC',(case.get('case_id'),))]
  profile['conviction_events']=[dict(x) for x in c.execute('SELECT * FROM conviction_events WHERE person_id=? ORDER BY event_date DESC',(pid,))]
  profile['identity_decisions']=[dict(x) for x in c.execute('SELECT decision,notes,reviewer,source,active,decided_at,updated_at,person_a,person_b FROM person_identity_decisions WHERE (person_a=? OR person_b=?) AND COALESCE(active,1)=1 ORDER BY COALESCE(updated_at,decided_at) DESC',(pid,pid))]
  profile['location_history']=sorted({x['signal_value'] for x in c.execute("SELECT signal_value FROM person_identity_signals WHERE person_id=? AND signal_type='case_location'",(pid,)) if x['signal_value']})
  profile['courthouse_history']=sorted({x['signal_value'] for x in c.execute("SELECT signal_value FROM person_identity_signals WHERE person_id=? AND signal_type='consistent_courthouse'",(pid,)) if x['signal_value']})
  sig=name_signature(profile.get('display_name')); profile['phonetic_first']=sig['phonetic_first']; profile['phonetic_last']=sig['phonetic_last']
  profiles.append(profile)
 payload={'generatedAt':now(),'people':profiles,'identityCandidates':[dict(x) for x in c.execute("SELECT ic.*,pa.display_name name_a,pb.display_name name_b,pa.birth_year birth_year_a,pb.birth_year birth_year_b FROM identity_candidates ic LEFT JOIN people pa ON pa.person_id=ic.person_a LEFT JOIN people pb ON pb.person_id=ic.person_b WHERE ic.status='open' ORDER BY match_score DESC")],'priorHistory':[dict(x) for x in c.execute('SELECT * FROM judgment_prior_history ORDER BY created_at DESC')]}
 DATA.mkdir(exist_ok=True); (DATA/'person-profiles.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8')
 # Rebuild the person index from permanent identities rather than one row per case.
 search_people=[]
 for profile in profiles:
  aliases=[a['alias_text'] for a in profile.get('aliases',[]) if a.get('alias_text')]
  cases=profile.get('cases',[]); offences=[]; courts=[]; locations=[]; outcomes=[]; citations=[]; files=[]
  for case in cases:
   courts.append(case.get('court_level') or '')
   location=(case.get('courthouse_slug') or '').replace('-',' ').title(); locations.append(location)
   outcomes.append(case.get('final_outcome') or case.get('legal_status') or '')
   citations.append(case.get('citation') or ''); files.append(case.get('court_file_number') or '')
   try: offences.extend([x['offence_text'] for x in c.execute('SELECT offence_text FROM charges WHERE case_id=?',(case.get('case_id'),))])
   except sqlite3.OperationalError: pass
  signal_map={x['signal_type']:x['signal_value'] for x in profile.get('signals',[])}
  fields=[profile.get('display_name'),*aliases,profile.get('birth_year'),profile.get('date_of_birth'),signal_map.get('middle_name'),*offences,*courts,*locations,*outcomes,*citations,*files]
  search_people.append({'id':profile['person_id'],'type':'person','title':profile.get('display_name') or 'Person','names':[profile.get('display_name') or ''],
   'name_variants':aliases,'birth_year':profile.get('birth_year') or (str(profile.get('date_of_birth') or '')[:4]),'middle_names':signal_map.get('middle_name') or '',
   'identity_confidence':profile.get('identity_confidence') or 0,'identity_status':profile.get('identity_status') or 'possible','phonetic_first':profile.get('phonetic_first') or '','phonetic_last':profile.get('phonetic_last') or '','common_name_frequency':sum(1 for x in profiles if name_signature(x.get('display_name')).get('last')==name_signature(profile.get('display_name')).get('last')), 'location_history':profile.get('location_history',[]),'courthouse_history':profile.get('courthouse_history',[]),'identity_signals':profile.get('signals',[]),'identity_decisions':profile.get('identity_decisions',[]),
   'court_file':next((x for x in files if x),''),'court_file_normalized':norm(next((x for x in files if x),'' )).replace(' ',''),
   'citation':next((x for x in citations if x),''),'offences':sorted(set(x for x in offences if x)),'outcome':next((x for x in outcomes if x),''),
   'sentence':'','court':' | '.join(sorted(set(x for x in courts if x))),'location':' | '.join(sorted(set(x for x in locations if x))),
   'date':max((str(x.get('outcome_date') or x.get('closed_date') or x.get('opened_date') or '') for x in cases),default=''),
   'verification':'verified' if profile.get('identity_status')=='verified' else 'review','source_url':next((x.get('source_url') for x in cases if x.get('source_url')),''),
   'search_normalized':norm(' '.join(str(x or '') for x in fields))})
 (DATA/'search-people.json').write_text(json.dumps({'generatedAt':now(),'records':search_people},indent=2,ensure_ascii=False),encoding='utf-8')
def main():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; setup(c)
 stats={'aliases':aliases(c),'offences':normalize_offences(c)}; stats['dispositions']=parse_dispositions(c); confidence(c); stats['identityCandidates']=build_identity_candidates(c); stats['convictionEvents']=events(c); stats['priorHistory']=prior_history(c); c.commit(); export(c); print(json.dumps(stats,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
