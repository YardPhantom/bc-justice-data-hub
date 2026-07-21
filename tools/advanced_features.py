#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json, re, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'database'/'bc_justice.db'; DATA=ROOT/'data'; IMPORTS=ROOT/'imports'
def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def norm(v): return re.sub(r'\W+',' ',str(v or '').lower()).strip()
def uid(*parts): return str(uuid.uuid5(uuid.NAMESPACE_URL,'|'.join(map(str,parts))))
def has_table(c,n): return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(n,)).fetchone() is not None

def setup(c):
 c.executescript('''
 CREATE TABLE IF NOT EXISTS prosecution_reports(report_id TEXT PRIMARY KEY,title TEXT,report_year TEXT,source_url TEXT,local_path TEXT,sha256 TEXT,retrieved_at TEXT,parse_status TEXT,raw_text TEXT);
 CREATE TABLE IF NOT EXISTS identity_candidates(candidate_id TEXT PRIMARY KEY,person_a TEXT,person_b TEXT,match_score REAL,reasons TEXT,status TEXT DEFAULT 'open',created_at TEXT);
 CREATE TABLE IF NOT EXISTS case_links(link_id TEXT PRIMARY KEY,case_id TEXT,entity_type TEXT,entity_id TEXT,match_method TEXT,match_score REAL,verified INTEGER DEFAULT 0,created_at TEXT);
 CREATE TABLE IF NOT EXISTS privacy_flags(flag_id TEXT PRIMARY KEY,entity_type TEXT,entity_id TEXT,flag_type TEXT,severity TEXT,details TEXT,status TEXT DEFAULT 'open',created_at TEXT);
 CREATE TABLE IF NOT EXISTS status_history(history_id TEXT PRIMARY KEY,case_id TEXT,status TEXT,event_date TEXT,source_type TEXT,source_id TEXT,verified INTEGER DEFAULT 0,created_at TEXT);
 CREATE TABLE IF NOT EXISTS comparison_cache(cache_id TEXT PRIMARY KEY,subject_area TEXT,geography TEXT,period TEXT,metric TEXT,current_value REAL,previous_value REAL,change_value REAL,change_percent REAL,province_value REAL,generated_at TEXT);
 CREATE TABLE IF NOT EXISTS dismissed_review_archive(archive_id INTEGER PRIMARY KEY AUTOINCREMENT,review_id TEXT,entity_type TEXT,entity_id TEXT,reason TEXT,severity TEXT,source_document_id TEXT,original_created_at TEXT,dismissed_at TEXT NOT NULL,dismissal_notes TEXT,action_json TEXT,UNIQUE(review_id),UNIQUE(entity_type,entity_id,reason));
 CREATE TRIGGER IF NOT EXISTS prevent_dismissed_review_requeue BEFORE INSERT ON review_queue WHEN EXISTS(SELECT 1 FROM dismissed_review_archive d WHERE d.review_id=NEW.review_id OR (COALESCE(d.entity_type,'')=COALESCE(NEW.entity_type,'') AND COALESCE(d.entity_id,'')=COALESCE(NEW.entity_id,'') AND COALESCE(d.reason,'')=COALESCE(NEW.reason,''))) BEGIN SELECT RAISE(IGNORE); END;
 ''')
 try:
  c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS justice_search USING fts5(entity_type,entity_id,title,body,source_url)")
 except sqlite3.OperationalError: pass
 c.commit()

def review(c,etype,eid,reason,severity='medium'):
 rid=uid(etype,eid,reason)
 c.execute("INSERT OR IGNORE INTO review_queue(review_id,entity_type,entity_id,reason,severity,status,created_at) VALUES(?,?,?,?,?,'open',?)",(rid,etype,eid,reason,severity,now()))

def prosecution(c):
 # Index locally downloaded BCPS reports and normalize obvious table rows already in staging.
 count=0
 for p in list((IMPORTS/'catalogue').glob('*prosecution*'))+list((IMPORTS/'catalogue').glob('*Crown*'))+list((IMPORTS/'documents').glob('*prosecution*')):
  rid=uid('prosecution',p.resolve()); title=p.stem; year=(re.search(r'20\d{2}(?:[-–/]\d{2,4})?',title) or [None])[0] or ''
  c.execute("INSERT OR IGNORE INTO prosecution_reports(report_id,title,report_year,local_path,retrieved_at,parse_status) VALUES(?,?,?,?,?,?)",(rid,title,year,str(p.relative_to(ROOT)).replace('\\','/'),now(),'indexed'))
  count+=1
 if has_table(c,'staging_rows'):
  for r in c.execute("SELECT staging_id,dataset_id,resource_id,raw_json FROM staging_rows WHERE lower(raw_json) LIKE '%charge%approved%' OR lower(raw_json) LIKE '%crown counsel%' OR lower(raw_json) LIKE '%alternative measures%'"):
   d=json.loads(r['raw_json']); keys={norm(k):v for k,v in d.items() if k is not None}; metric=''; val=None
   for k,v in keys.items():
    if any(x in k for x in ('approved','not approved','alternative measures','reports to crown')):
     metric=k; 
     try: val=float(str(v).replace(',','').replace('%',''))
     except: continue
     sid=uid('pros',r['staging_id'],k)
     c.execute("INSERT OR IGNORE INTO prosecution_statistics(stat_id,region,fiscal_year,metric,value,unit,dataset_id,resource_id,raw_json) VALUES(?,?,?,?,?,?,?,?,?)",(sid,str(keys.get('region','')),str(keys.get('fiscal year') or keys.get('year') or ''),metric,val,'percent' if '%' in str(v) else 'count',r['dataset_id'],r['resource_id'],r['raw_json']))
 return count

def duplicate_people(c):
 c.execute('DELETE FROM identity_candidates WHERE status="open"')
 people=[dict(r) for r in c.execute('SELECT person_id,display_name,normalized_name,date_of_birth FROM people')]
 groups={}
 for p in people: groups.setdefault(norm(p['normalized_name'] or p['display_name']),[]).append(p)
 n=0
 for name,items in groups.items():
  if not name or len(items)<2: continue
  for i,a in enumerate(items):
   for b in items[i+1:]:
    score=.75; reasons=['same normalized name']
    if a['date_of_birth'] and b['date_of_birth'] and a['date_of_birth']==b['date_of_birth']: score=.98; reasons.append('same date of birth')
    # Mention-level court, file and event overlap strengthen identity review scoring.
    if has_table(c,'person_mentions'):
     ma=[dict(x) for x in c.execute('SELECT court_file_number,court,location,event_date FROM person_mentions WHERE person_id=?',(a['person_id'],))]
     mb=[dict(x) for x in c.execute('SELECT court_file_number,court,location,event_date FROM person_mentions WHERE person_id=?',(b['person_id'],))]
     files_a={x['court_file_number'] for x in ma if x['court_file_number']}; files_b={x['court_file_number'] for x in mb if x['court_file_number']}
     loc_a={str(x['location'] or x['court'] or '').casefold() for x in ma if x['location'] or x['court']}; loc_b={str(x['location'] or x['court'] or '').casefold() for x in mb if x['location'] or x['court']}
     if files_a & files_b: score=max(score,.97); reasons.append('same court file')
     elif loc_a & loc_b: score=max(score,.84); reasons.append('shared court or location')
    cid=uid('dupe',a['person_id'],b['person_id'])
    c.execute('INSERT OR REPLACE INTO identity_candidates VALUES(?,?,?,?,?,?,?)',(cid,a['person_id'],b['person_id'],score,'; '.join(reasons),'open',now())); review(c,'identity_candidate',cid,'Possible duplicate person records','high' if score>.9 else 'medium'); n+=1
 return n

def timelines(c):
 c.execute('DELETE FROM status_history')
 n=0
 for r in c.execute('SELECT case_id,legal_status,opened_date,retrieved_at,verification_state FROM cases'):
  if r['legal_status']:
   c.execute('INSERT OR IGNORE INTO status_history VALUES(?,?,?,?,?,?,?,?)',(uid(r['case_id'],'case',r['legal_status']),r['case_id'],r['legal_status'],r['opened_date'] or r['retrieved_at'],'case',r['case_id'],1 if r['verification_state']=='verified' else 0,now())); n+=1
 for r in c.execute('SELECT event_id,case_id,event_type,event_date,verification_state FROM case_events'):
  c.execute('INSERT OR IGNORE INTO status_history VALUES(?,?,?,?,?,?,?,?)',(uid(r['case_id'],'event',r['event_id']),r['case_id'],r['event_type'],r['event_date'],'case_event',r['event_id'],1 if r['verification_state']=='verified' else 0,now())); n+=1
 for r in c.execute('SELECT outcome_id,case_id,outcome_type,outcome_date,verified FROM outcomes'):
  c.execute('INSERT OR IGNORE INTO status_history VALUES(?,?,?,?,?,?,?,?)',(uid(r['case_id'],'outcome',r['outcome_id']),r['case_id'],r['outcome_type'],r['outcome_date'],'outcome',r['outcome_id'],r['verified'],now())); n+=1
 # Add exact court-file matches as scheduled appearances only. These remain
 # unverified appearances and never imply a charge, finding, or conviction.
 if has_table(c,'daily_appearances'):
  for r in c.execute('''
   SELECT c.case_id,a.appearance_id,a.list_date,a.legal_status
   FROM cases c JOIN daily_appearances a
    ON lower(replace(replace(replace(trim(c.court_file_number),' ',''),'-',''),'.',''))
     = lower(replace(replace(replace(trim(a.court_file_number),' ',''),'-',''),'.',''))
   WHERE COALESCE(trim(c.court_file_number),'')<>''
     AND COALESCE(trim(a.court_file_number),'')<>''
     AND COALESCE(a.is_current,1)=1
  '''):
   status=r['legal_status'] or 'scheduled_appearance'
   c.execute('INSERT OR IGNORE INTO status_history VALUES(?,?,?,?,?,?,?,?)',(uid(r['case_id'],'appearance',r['appearance_id']),r['case_id'],status,r['list_date'],'daily_appearance',r['appearance_id'],0,now())); n+=1
 return n

def enrich_judgments(c):
 n=0
 if not has_table(c,'published_judgments'): return 0
 cols={x[1] for x in c.execute('PRAGMA table_info(published_judgments)')}
 for spec in ['sentence_text TEXT','publication_flags TEXT','extraction_confidence REAL DEFAULT 0']:
  if spec.split()[0] not in cols: c.execute(f'ALTER TABLE published_judgments ADD COLUMN {spec}')
 for r in c.execute('SELECT * FROM published_judgments'):
  text=' '.join(str(r[k] or '') for k in r.keys()).lower(); outcome=''
  rules=[('acquitted',r'\bacquitt(?:ed|al)\b|not guilty'),('stayed',r'charges? (?:were )?stayed|stay of proceedings'),('convicted',r'\bconvict(?:ed|ion)\b|found guilty'),('dismissed',r'appeal dismissed'),('withdrawn',r'charges? withdrawn')]
  hits=[o for o,p in rules if re.search(p,text)]
  if len(hits)==1: outcome=hits[0]
  sentence=''; sm=re.search(r'(?:sentenced? to|sentence(?:d)?(?: of)?)[^.;]{0,220}',text,re.I)
  if sm: sentence=sm.group(0)
  flags=[]
  for label,pat in [('publication ban',r'publication ban|s\.\s*486'),('youth',r'youth criminal justice act|young person'),('sexual offence',r'sexual assault|sexual interference')]:
   if re.search(pat,text,re.I): flags.append(label)
  conf=.85 if outcome else .25
  c.execute('UPDATE published_judgments SET outcome_type=COALESCE(NULLIF(outcome_type,\'\'),?),sentence_text=?,publication_flags=?,extraction_confidence=? WHERE judgment_id=?',(outcome,sentence,', '.join(flags),conf,r['judgment_id']))
  if outcome or flags: n+=1
  if flags: review(c,'published_judgment',r['judgment_id'],'Review publication restriction or protected identity','high')
 return n

def link_records(c):
 c.execute('DELETE FROM case_links WHERE verified=0')
 n=0
 # Match court-list appearances by normalized court-file number, with courthouse as supporting evidence.
 if has_table(c,'daily_appearances'):
  rows=c.execute("""
   SELECT c.case_id,a.appearance_id,
          CASE WHEN COALESCE(c.courthouse_slug,'')=COALESCE(a.courthouse_slug,'') AND COALESCE(c.courthouse_slug,'')<>'' THEN 0.9 ELSE 0.8 END AS score,
          CASE WHEN COALESCE(c.courthouse_slug,'')=COALESCE(a.courthouse_slug,'') AND COALESCE(c.courthouse_slug,'')<>'' THEN 'file number, courthouse' ELSE 'file number' END AS method
   FROM cases c
   JOIN daily_appearances a
     ON lower(replace(replace(replace(trim(c.court_file_number),' ',''),'-',''),'.',''))
      = lower(replace(replace(replace(trim(a.court_file_number),' ',''),'-',''),'.',''))
   WHERE COALESCE(trim(c.court_file_number),'')<>''
     AND COALESCE(trim(a.court_file_number),'')<>''
  """).fetchall()
  for r in rows:
   lid=uid('link',r['case_id'],'daily',r['appearance_id'])
   c.execute('INSERT OR IGNORE INTO case_links VALUES(?,?,?,?,?,?,?,?)',(lid,r['case_id'],'daily_appearance',r['appearance_id'],r['method'],r['score'],0,now()))
   n+=1
 if has_table(c,'published_judgments'):
  # Prefer exact normalized citations. Fall back to exact normalized case titles only when citations do not match.
  rows=c.execute("""
   SELECT c.case_id,j.judgment_id,0.95 AS score,'citation' AS method
   FROM cases c JOIN published_judgments j
     ON lower(replace(replace(trim(c.citation),' ',''),'.',''))=lower(replace(replace(trim(j.citation),' ',''),'.',''))
   WHERE COALESCE(trim(c.citation),'')<>'' AND COALESCE(trim(j.citation),'')<>''
   UNION ALL
   SELECT c.case_id,j.judgment_id,0.75 AS score,'case title' AS method
   FROM cases c JOIN published_judgments j
     ON lower(trim(c.case_title))=lower(trim(j.case_title))
   WHERE COALESCE(trim(c.case_title),'')<>'' AND COALESCE(trim(j.case_title),'')<>''
     AND NOT EXISTS (
       SELECT 1 FROM published_judgments j2
       WHERE COALESCE(trim(c.citation),'')<>'' AND COALESCE(trim(j2.citation),'')<>''
         AND lower(replace(replace(trim(c.citation),' ',''),'.',''))=lower(replace(replace(trim(j2.citation),' ',''),'.',''))
     )
  """).fetchall()
  for r in rows:
   lid=uid('link',r['case_id'],'judgment',r['judgment_id'])
   c.execute('INSERT OR IGNORE INTO case_links VALUES(?,?,?,?,?,?,?,?)',(lid,r['case_id'],'judgment',r['judgment_id'],r['method'],r['score'],0,now()))
   review(c,'case_link',lid,'Verify automatic case link','medium')
   n+=1
 return n

def privacy(c):
 c.execute('DELETE FROM privacy_flags WHERE status="open"'); n=0
 if has_table(c,'published_judgments'):
  for r in c.execute('SELECT judgment_id,case_title,publication_flags FROM published_judgments'):
   txt=(r['case_title'] or '')+' '+(r['publication_flags'] or '')
   if re.search(r'\bR\.\s*v\.\s*[A-Z](?:\.|\b)|youth|publication ban',txt,re.I):
    fid=uid('privacy','judgment',r['judgment_id']); c.execute('INSERT OR REPLACE INTO privacy_flags VALUES(?,?,?,?,?,?,?,?)',(fid,'published_judgment',r['judgment_id'],'protected identity','high',txt[:500],'open',now())); review(c,'privacy_flag',fid,'Protected identity or publication restriction detected','high'); n+=1
 # Named youth records in cases must be reviewed.
 for r in c.execute("SELECT cp.case_id,p.person_id,p.display_name,c.case_title FROM case_people cp JOIN people p ON p.person_id=cp.person_id JOIN cases c ON c.case_id=cp.case_id WHERE lower(c.case_title) LIKE '%youth%' OR lower(c.notes) LIKE '%youth%'"):
  fid=uid('privacy','person',r['person_id']); c.execute('INSERT OR REPLACE INTO privacy_flags VALUES(?,?,?,?,?,?,?,?)',(fid,'person',r['person_id'],'possible youth identity','critical',r['display_name'],'open',now())); review(c,'privacy_flag',fid,'Possible identifiable youth record','critical'); n+=1
 return n

def _number(v):
 if v is None or isinstance(v,bool): return None
 text=str(v).strip().replace(',','').replace('$','')
 if not text or text.lower() in {'n/a','na','null','none','-','—'}: return None
 pct='%' in text
 text=text.replace('%','')
 try:return float(text),('percent' if pct else 'count')
 except (TypeError,ValueError): return None

def _custody_metric_fields(d):
 """Yield metric/value/unit triples from long- and wide-form custody rows."""
 items=[(str(k or '').strip(),v) for k,v in d.items()]
 descriptor=' · '.join(str(v).strip() for k,v in items if any(x in norm(k) for x in ('metric','measure','indicator','statistic','category','type','status')) and str(v or '').strip())
 value_keys=('value','count','total','number','rate','percent','percentage','amount','estimate')
 skip_keys=('year','period','date','month','quarter','fiscal','id','code','postal','latitude','longitude')
 custody_terms=('remand','sentenced','admission','release','length of stay','daily population','average daily','custody','inmate','offender','capacity','occupancy','confinement','incarcerat','population')
 yielded=set()
 # Long-form rows: descriptor column plus a generic numeric value column.
 if descriptor:
  for k,v in items:
   key=norm(k)
   if any(x in key for x in value_keys):
    parsed=_number(v)
    if parsed:
     token=(descriptor,key)
     if token not in yielded:
      yielded.add(token); yield descriptor,parsed[0],parsed[1]
 # Wide-form rows: metric is encoded in the numeric column heading.
 for k,v in items:
  key=norm(k)
  if not key or any(x in key for x in skip_keys): continue
  if not any(x in key for x in custody_terms): continue
  parsed=_number(v)
  if parsed:
   token=(k,key)
   if token not in yielded:
    yielded.add(token); yield k,parsed[0],parsed[1]

def adult_custody(c):
 n=0
 if not has_table(c,'staging_rows'):
  print('Adult custody: no staging rows table found; skipping.', flush=True); return 0
 total=c.execute('SELECT COUNT(*) FROM staging_rows').fetchone()[0]
 if not total:
  print('Adult custody: no staged rows to scan.', flush=True); return 0
 has_catalogue=has_table(c,'catalogue_datasets') and has_table(c,'catalogue_resources')
 max_rowid=c.execute('SELECT COALESCE(MAX(rowid),0) FROM staging_rows').fetchone()[0]
 batch_size=2000; last_rowid=0; scanned=0; candidates=0; last_reported_percent=0
 terms=('adult custody','custod','remand','sentenced custody','correction','confinement','incarcerat')
 like_sql=' OR '.join(['lower(s.raw_json) LIKE ?']*len(terms))
 params_like=tuple(f'%{term}%' for term in terms)
 if has_catalogue:
  context_sql=' OR '.join([like_sql,"lower(COALESCE(d.title,'')) LIKE ?","lower(COALESCE(cr.name,'')) LIKE ?"])
  query=("SELECT s.rowid AS _rowid,s.staging_id,s.dataset_id,s.resource_id,s.raw_json, "
         "COALESCE(d.title,'') dataset_title,COALESCE(cr.name,'') resource_name "
         "FROM staging_rows s LEFT JOIN catalogue_datasets d ON d.dataset_id=s.dataset_id "
         "LEFT JOIN catalogue_resources cr ON cr.resource_id=s.resource_id "
         f"WHERE s.rowid>? AND ({context_sql}) ORDER BY s.rowid LIMIT ?")
 else:
  query=("SELECT s.rowid AS _rowid,s.staging_id,s.dataset_id,s.resource_id,s.raw_json, "
         "'' dataset_title,'' resource_name FROM staging_rows s "
         f"WHERE s.rowid>? AND ({like_sql}) ORDER BY s.rowid LIMIT ?")
 print(f'Adult custody: scanning likely custody rows from {total:,} staged rows in batches of {batch_size}.', flush=True)
 pending=[]
 while True:
  if has_catalogue:
   args=(last_rowid,*params_like,'%custod%','%custod%',batch_size)
  else:
   args=(last_rowid,*params_like,batch_size)
  rows=c.execute(query,args).fetchall()
  if not rows: break
  pending.clear()
  for r in rows:
   last_rowid=r['_rowid']; scanned+=1
   raw=str(r['raw_json'] or '')
   try:d=json.loads(raw)
   except (TypeError,ValueError): continue
   if not isinstance(d,dict): continue
   extracted=list(_custody_metric_fields(d))
   if not extracted: continue
   candidates+=1
   context=' '.join((str(r['dataset_title'] or ''),str(r['resource_name'] or ''),raw)).lower()
   items=[(str(k or ''),v) for k,v in d.items()]
   facility=next((str(v) for k,v in items if any(x in norm(k) for x in ('facility','centre','institution','custody centre')) and str(v or '').strip()),'British Columbia' if 'british columbia' in context else '')
   region=next((str(v) for k,v in items if any(x in norm(k) for x in ('region','geography','location')) and str(v or '').strip()),'')
   period=next((str(v) for k,v in items if any(x in norm(k) for x in ('period','fiscal year','year','month','ref date','reference date')) and str(v or '').strip()),'')
   for metric,val,unit in extracted:
    sid=uid('adultcust',r['staging_id'],metric)
    pending.append((sid,facility,region,period,metric,val,unit,r['dataset_id'],r['resource_id'],raw)); n+=1
  if pending:
   c.executemany('INSERT OR REPLACE INTO custody_statistics(stat_id,facility,region,period,metric,value,unit,dataset_id,resource_id,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?)',pending)
  percent=min(100,int(last_rowid*100/max_rowid)) if max_rowid else 100
  reported_percent=(percent//2)*2
  if reported_percent>=2 and reported_percent>last_reported_percent:
   width=24; filled=min(width,int(reported_percent*width/100)); bar='#'*filled+'-'*(width-filled)
   print(f'Adult custody: [{bar}] {reported_percent:3d}% | checked through row {last_rowid:,}/{max_rowid:,} | likely rows {scanned:,} | candidates {candidates:,} | extracted {n:,}', flush=True); last_reported_percent=reported_percent
 if last_reported_percent<100: print(f"Adult custody: [{'#'*24}] 100% | checked through row {max_rowid:,}/{max_rowid:,} | likely rows {scanned:,} | candidates {candidates:,} | extracted {n:,}", flush=True)
 print(f'Adult custody: scan complete; {candidates:,} candidate rows produced {n:,} statistics.', flush=True)
 return n

def comparisons(c):
 c.execute('DELETE FROM comparison_cache'); n=0
 tables=[('court_statistics','courthouse_slug','fiscal_year'),('crime_statistics','geography','year'),('custody_statistics','facility','period'),('youth_justice_statistics','geography','period'),('civil_forfeiture_statistics','geography','period')]
 for table,geo,period in tables:
  if not has_table(c,table): continue
  rows=[dict(r) for r in c.execute(f'''SELECT {geo} geography,{period} period,metric,AVG(value) value
      FROM {table}
      WHERE value IS NOT NULL
      GROUP BY {geo},{period},metric''')]
  groups={}
  for r in rows: groups.setdefault((r['geography'] or '',r['metric'] or ''),[]).append(r)
  for (g,m),vals in groups.items():
   vals=sorted(vals,key=lambda x:str(x['period']))
   for i,r in enumerate(vals):
    prev=vals[i-1]['value'] if i else None; change=(r['value']-prev) if prev is not None else None; pct=(change/prev*100) if prev not in (None,0) else None
    cid=uid(table,g,m,r['period']); c.execute('INSERT OR REPLACE INTO comparison_cache VALUES(?,?,?,?,?,?,?,?,?,?,?)',(cid,table,g,r['period'],m,r['value'],prev,change,pct,None,now())); n+=1
 return n

def search_index(c):
 try: c.execute('DELETE FROM justice_search')
 except sqlite3.OperationalError: return 0
 n=0
 for r in c.execute('SELECT case_id,case_title,court_file_number,legal_status,final_outcome,source_url FROM cases'):
  c.execute('INSERT INTO justice_search VALUES(?,?,?,?,?)',('case',r['case_id'],r['case_title'] or r['court_file_number'],' '.join(str(r[k] or '') for k in r.keys()),r['source_url'] or '')); n+=1
 if has_table(c,'published_judgments'):
  for r in c.execute('SELECT * FROM published_judgments'):
   c.execute('INSERT INTO justice_search VALUES(?,?,?,?,?)',('judgment',r['judgment_id'],r['case_title'],' '.join(str(r[k] or '') for k in r.keys()),r['source_url'])); n+=1
 return n


def repeat_offenders(c):
 groups=[]
 severity={'other offences':1,'environmental and regulatory':1,'driving and traffic':2,'public order':2,'administration of justice':2,'drug offences':3,'property':3,'fraud and financial':3,'weapons and firearms':4,'violence':5,'sexual offences':5}
 def split_groups(value): return sorted({x.strip() for x in re.split(r'\s*,\s*',value or '') if x.strip()})
 def event_year(value):
  m=re.search(r'\b(19\d{2}|20\d{2})\b',str(value or '')); return int(m.group(1)) if m else None
 def trend(events):
  dated=[e for e in events if e.get('event_date')]
  if len(dated)<2:return 'insufficient history'
  dated.sort(key=lambda e:str(e.get('event_date') or ''))
  first=max((severity.get(g,1) for g in split_groups(dated[0].get('offence_groups'))),default=1); latest=max((severity.get(g,1) for g in split_groups(dated[-1].get('offence_groups'))),default=1)
  return 'higher-severity category later' if latest>first else 'lower-severity category later' if latest<first else 'similar category severity'
 def coverage(events,priors):
  years=sorted({event_year(e.get('offence_date') or e.get('event_date')) for e in events if event_year(e.get('offence_date') or e.get('event_date'))})
  if len(years)>=4 and years[0]<=2005:return 'strong'
  if len(years)>=2 and years[0]<=2015:return 'partial'
  if years:return 'recent years only'
  if priors:return 'judgment-reported history only'
  return 'unknown'
 def missing_alert(events,priors):
  verified=len(events); reported=max([int(x.get('total_prior_convictions') or 0) for x in priors] or [0]); text=' '.join(str(x.get('description') or '') for x in priors).lower()
  qualitative=bool(re.search(r'\b(?:lengthy|extensive|numerous|significant|substantial)\s+(?:criminal\s+)?record\b',text))
  if reported>verified:return f'Judgment reports {reported} prior convictions; only {verified} independently verified event(s) are indexed.'
  if qualitative and verified<5:return 'Judgment describes a substantial prior record, but the indexed verified history appears incomplete.'
  return ''
 def sequence(events):
  ordered=sorted([e for e in events if e.get('event_date')],key=lambda e:str(e.get('event_date')))
  out=[]; previous=None
  for e in ordered:
   year=event_year(e.get('offence_date') or e.get('event_date')); gap=(year-previous) if year is not None and previous is not None else None
   out.append({'event_id':e.get('event_id'),'case_id':e.get('case_id'),'case_title':e.get('case_title'),'court_file_number':e.get('court_file_number'),'citation':e.get('citation'),'courthouse':e.get('courthouse_slug'),'source_url':e.get('source_url'),'final_outcome':e.get('final_outcome'),'sentence_summary':e.get('sentence_summary'),'source_type':e.get('source_type'),'source_quality':e.get('source_quality'),'offence_date':e.get('offence_date'),'conviction_date':e.get('conviction_date') or e.get('event_date'),'offence_groups':split_groups(e.get('offence_groups')),'linked_case_ids':json.loads(e.get('linked_case_ids') or '[]') if isinstance(e.get('linked_case_ids'),str) else (e.get('linked_case_ids') or []),'proceeding_types':json.loads(e.get('proceeding_types') or '[]') if isinstance(e.get('proceeding_types'),str) else (e.get('proceeding_types') or []),'gap_years':gap})
   if year is not None:previous=year
  return out
 def duplicate_evidence(person_id):
  if not has_table(c,'identity_candidates'): return []
  rows=[]
  for x in c.execute("""SELECT candidate_id,person_a,person_b,match_score,reasons,status FROM identity_candidates WHERE (person_a=? OR person_b=?) AND COALESCE(status,'open')='open' ORDER BY match_score DESC""",(person_id,person_id)):
   other=x['person_b'] if x['person_a']==person_id else x['person_a']
   person=c.execute('SELECT display_name,birth_year,date_of_birth FROM people WHERE person_id=?',(other,)).fetchone()
   rows.append({'candidate_id':x['candidate_id'],'other_person_id':other,'other_display_name':person['display_name'] if person else other,'confidence':x['match_score'],'reasons':x['reasons'],'birth_year':person['birth_year'] if person else None,'date_of_birth_match':False})
  return rows
 def identity_evidence(person,events,aliases):
  evidence=[]
  if person['identity_status']=='verified': evidence.append('identity record marked verified')
  if person['date_of_birth']: evidence.append('date of birth recorded')
  elif person['birth_year']: evidence.append('birth year recorded')
  if len(set(aliases))>1: evidence.append(f'{len(set(aliases))} linked name variants')
  files={e.get('court_file_number') for e in events if e.get('court_file_number')}
  courts={e.get('courthouse_slug') for e in events if e.get('courthouse_slug')}
  if len(files)>=2: evidence.append(f'{len(files)} distinct court files')
  if courts: evidence.append(f'{len(courts)} courthouse location(s)')
  return evidence
 prior_by_person={}
 if has_table(c,'judgment_prior_history'):
  for r in c.execute('SELECT * FROM judgment_prior_history WHERE person_id IS NOT NULL ORDER BY confidence DESC'):
   prior_by_person.setdefault(r['person_id'],[]).append(dict(r))
 if has_table(c,'conviction_events'):
  persons=c.execute("""SELECT DISTINCT p.person_id,p.display_name,p.identity_confidence,p.identity_status,p.birth_year,p.date_of_birth FROM people p JOIN conviction_events ce ON ce.person_id=p.person_id WHERE ce.verified=1""").fetchall()
  for p in persons:
   events=[dict(x) for x in c.execute("""SELECT ce.*,c.courthouse_slug,c.court_file_number,c.case_title,c.source_url,c.citation,c.final_outcome,(SELECT group_concat(o.sentence_summary,'; ') FROM outcomes o WHERE o.case_id=ce.case_id AND o.verified=1 AND COALESCE(o.sentence_summary,'')<>'') sentence_summary FROM conviction_events ce LEFT JOIN cases c ON c.case_id=ce.case_id WHERE ce.person_id=? AND ce.verified=1 ORDER BY COALESCE(ce.offence_date,ce.event_date),ce.conviction_date""",(p['person_id'],))]
   priors=prior_by_person.get(p['person_id'],[]); distinct=len({e['event_id'] for e in events}); reported=max([int(x.get('total_prior_convictions') or 0) for x in priors] or [0])
   if distinct<2 and not (distinct>=1 and reported>0): continue
   categories=[]; years=[]; courthouses=[]
   for e in events:
    categories.extend(split_groups(e.get('offence_groups'))); y=event_year(e.get('offence_date') or e.get('event_date'))
    if y is not None:years.append(y)
    if e.get('courthouse_slug'):courthouses.append(e['courthouse_slug'])
   category_counts={g:categories.count(g) for g in sorted(set(categories))}; repeated=sorted(g for g,n in category_counts.items() if n>=2)
   breach=sum(1 for e in events if 'administration of justice' in split_groups(e.get('offence_groups')) or re.search(r'\b(?:breach|probation|failure to comply|recognizance)\b',str(e.get('offence_groups') or ''),re.I))
   dy=sorted(set(years)); first=next((e.get('offence_date') or e.get('event_date') for e in events if e.get('offence_date') or e.get('event_date')),None); latest=next((e.get('conviction_date') or e.get('event_date') for e in reversed(events) if e.get('conviction_date') or e.get('event_date')),None)
   aliases=[x['alias_text'] for x in c.execute('SELECT alias_text FROM person_aliases WHERE person_id=? ORDER BY verified DESC,alias_text',(p['person_id'],))] if has_table(c,'person_aliases') else [p['display_name']]
   classification='confirmed_repeat_convictions' if distinct>=2 else 'verified_plus_reported_prior_history'
   seq=sequence(events); alert=missing_alert(events,priors)
   groups.append({'person_id':p['person_id'],'display_name':p['display_name'],'name_variants':aliases,'classification':classification,'identity_verified':p['identity_status']=='verified','identity_status':p['identity_status'],'identity_confidence':p['identity_confidence'],'verified_conviction_count':distinct,'conviction_event_count':distinct,'reported_prior_conviction_count':reported,'reported_prior_history':priors,'convicted_charge_count':sum(int(e.get('convicted_charge_count') or 0) for e in events),'first_conviction':first,'latest_conviction':latest,'conviction_years':dy,'active_year_count':len(dy),'years_active':(max(dy)-min(dy)+1) if len(dy)>=2 else (1 if dy else 0),'offence_groups':sorted(set(categories)),'offence_group_counts':category_counts,'repeated_offence_groups':repeated,'same_category_repetition':bool(repeated),'cross_category_repetition':len(set(categories))>=2,'breach_probation_event_count':breach,'pattern_trend':trend(events),'courthouses':sorted(set(courthouses)),'profile_url':'person-profile.html?id='+p['person_id'],'historical_coverage':coverage(events,priors),'missing_history_alert':alert,'conviction_sequence':seq,'linked_proceeding_count':sum(max(0,len(x.get('linked_case_ids') or [])-1) for x in seq),'max_gap_years':max([x.get('gap_years') or 0 for x in seq] or [0]),'birth_year':p['birth_year'],'identity_evidence':identity_evidence(p,events,aliases),'duplicate_candidates':duplicate_evidence(p['person_id']),'has_custodial_sentence':any(re.search(r'\b(?:custody|jail|imprison|incarcerat|days?|months?|years?)\b',str(e.get('sentence_summary') or ''),re.I) for e in events)})
 existing={x['person_id'] for x in groups}
 for r in c.execute("""SELECT p.person_id,p.display_name,p.identity_confidence,p.identity_status,p.birth_year,p.date_of_birth,COUNT(DISTINCT cp.case_id) case_count FROM people p JOIN case_people cp ON cp.person_id=p.person_id GROUP BY p.person_id HAVING COUNT(DISTINCT cp.case_id)>=2""").fetchall():
  if r['person_id'] in existing:continue
  priors=prior_by_person.get(r['person_id'],[])
  groups.append({'person_id':r['person_id'],'display_name':r['display_name'],'name_variants':[r['display_name']],'classification':'possible_repeat_case_name','identity_verified':r['identity_status']=='verified','identity_status':r['identity_status'],'identity_confidence':r['identity_confidence'],'verified_conviction_count':0,'conviction_event_count':0,'reported_prior_conviction_count':max([int(x.get('total_prior_convictions') or 0) for x in priors] or [0]),'reported_prior_history':priors,'convicted_charge_count':0,'case_count':r['case_count'],'appearance_count':0,'appearance_dates':[],'court_file_numbers':[],'conviction_years':[],'active_year_count':0,'years_active':0,'offence_groups':[],'offence_group_counts':{},'repeated_offence_groups':[],'same_category_repetition':False,'cross_category_repetition':False,'breach_probation_event_count':0,'pattern_trend':'not applicable','courthouses':[],'profile_url':'person-profile.html?id='+r['person_id'],'historical_coverage':'judgment-reported history only' if priors else 'unknown','missing_history_alert':missing_alert([],priors),'conviction_sequence':[],'linked_proceeding_count':0,'max_gap_years':0,'birth_year':r['birth_year'],'identity_evidence':identity_evidence(r,[],[r['display_name']]),'duplicate_candidates':duplicate_evidence(r['person_id']),'has_custodial_sentence':False})

 # Court-list names are recurrence evidence only. They are never treated as convictions or a confirmed identity.
 appearance_by_name={}
 if has_table(c,'daily_appearances'):
  for a in c.execute('SELECT participant_name,list_date,court_file_number,courthouse_name,courthouse_slug,appearance_id FROM daily_appearances WHERE participant_name IS NOT NULL'):
   display=' '.join(str(a['participant_name'] or '').split()); key=norm(display)
   # Exclude empty, initials-only, anonymized and generic labels from recurrence grouping.
   words=[w for w in key.split() if w]
   if not key or len(words)<2 or all(len(w)<=1 for w in words) or key in {'unknown person','john doe','jane doe','young person'}:continue
   item=appearance_by_name.setdefault(key,{'display_names':{},'events':set(),'dates':set(),'files':set(),'courthouses':set()})
   item['display_names'][display]=item['display_names'].get(display,0)+1
   date=str(a['list_date'] or ''); file_no=str(a['court_file_number'] or ''); aid=str(a['appearance_id'] or '')
   # A file/date pair is one recurrence event; appearance id is the last-resort key.
   event=(date,norm(file_no)) if date or file_no else ('',aid)
   item['events'].add(event)
   if date:item['dates'].add(date)
   if file_no:item['files'].add(file_no)
   court=str(a['courthouse_name'] or a['courthouse_slug'] or '')
   if court:item['courthouses'].add(court)

 by_normalized={}
 for r in groups:
  for name in [r.get('display_name')]+list(r.get('name_variants') or []):
   if norm(name):by_normalized.setdefault(norm(name),r)
 for key,item in appearance_by_name.items():
  count=len(item['events'])
  if count<2:continue
  display=max(item['display_names'],key=item['display_names'].get)
  existing_record=by_normalized.get(key)
  if existing_record:
   existing_record['appearance_count']=count; existing_record['appearance_dates']=sorted(item['dates']); existing_record['court_file_numbers']=sorted(item['files']); existing_record['courthouses']=sorted(set(existing_record.get('courthouses') or [])|item['courthouses'])
   continue
  groups.append({'person_id':'appearance-name-'+uid('appearance-name',key),'display_name':display,'name_variants':sorted(item['display_names']),'classification':'repeat_appearances_only','identity_verified':False,'identity_status':'unlinked recurring court-list name','identity_confidence':0.2,'verified_conviction_count':0,'conviction_event_count':0,'reported_prior_conviction_count':0,'reported_prior_history':[],'convicted_charge_count':0,'case_count':0,'appearance_count':count,'appearance_dates':sorted(item['dates']),'court_file_numbers':sorted(item['files']),'conviction_years':[],'active_year_count':0,'years_active':0,'offence_groups':[],'offence_group_counts':{},'repeated_offence_groups':[],'same_category_repetition':False,'cross_category_repetition':False,'breach_probation_event_count':0,'pattern_trend':'court-list recurrence only','courthouses':sorted(item['courthouses']),'profile_url':'search.html?q='+display.replace(' ','%20')+'&type=people','historical_coverage':'court-list appearances only','missing_history_alert':'','conviction_sequence':[],'linked_proceeding_count':0,'max_gap_years':0,'birth_year':None,'identity_evidence':['normalized recurring court-list name only'],'duplicate_candidates':[],'has_custodial_sentence':False})

 groups.sort(key=lambda r:(r.get('classification')=='confirmed_repeat_convictions',r.get('conviction_event_count',0),r.get('reported_prior_conviction_count',0),r.get('appearance_count',0),r.get('case_count',0),r['display_name']),reverse=True)
 confirmed=[r for r in groups if r['classification']=='confirmed_repeat_convictions']; reported=[r for r in groups if r['classification']=='verified_plus_reported_prior_history']; appearances=[r for r in groups if r['classification']=='repeat_appearances_only']
 payload={'generatedAt':now(),'notice':'Confirmed repeat offending requires at least two distinct verified conviction events. Repeat court-list names are shown separately and do not establish identity, guilt, or conviction.','counts':{'listedNames':len(groups),'confirmedRepeatConvictions':len(confirmed),'verifiedPlusReportedHistory':len(reported),'reportedPriorHistoryRecords':sum(bool(r.get('reported_prior_conviction_count')) for r in groups),'possibleRepeatCaseNames':sum(r['classification']=='possible_repeat_case_name' for r in groups),'repeatAppearancesOnly':len(appearances),'sameCategoryRepeaters':sum(bool(r.get('same_category_repetition')) for r in confirmed),'crossCategoryRepeaters':sum(bool(r.get('cross_category_repetition')) for r in confirmed),'breachProbationPatterns':sum((r.get('breach_probation_event_count') or 0)>0 for r in confirmed),'missingHistoryAlerts':sum(bool(r.get('missing_history_alert')) for r in groups),'linkedProceedings':sum(int(r.get('linked_proceeding_count') or 0) for r in groups)},'records':groups}
 DATA.mkdir(exist_ok=True); (DATA/'repeat-offenders.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); return len(groups)

def export(c):
 def rows(q): return [dict(r) for r in c.execute(q)]
 payload={
  'generatedAt':now(),
  'duplicates':rows("SELECT ic.*,pa.display_name name_a,pb.display_name name_b FROM identity_candidates ic LEFT JOIN people pa ON pa.person_id=ic.person_a LEFT JOIN people pb ON pb.person_id=ic.person_b WHERE ic.status='open' ORDER BY match_score DESC LIMIT 5000"),
  'links':rows('SELECT * FROM case_links ORDER BY match_score DESC LIMIT 10000'),
  'privacy':rows("SELECT * FROM privacy_flags WHERE status='open' ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 ELSE 3 END LIMIT 5000"),
  'timelines':rows('''
   SELECT h.*,c.court_file_number,c.citation,c.case_title,c.courthouse_slug,c.legal_status AS current_status,c.verification_state,
          COALESCE((SELECT group_concat(DISTINCT p.display_name) FROM case_people cp JOIN people p ON p.person_id=cp.person_id WHERE cp.case_id=c.case_id),'') AS people,
          COALESCE((SELECT group_concat(DISTINCT ch.offence_text) FROM charges ch WHERE ch.case_id=c.case_id AND COALESCE(ch.offence_text,'')<>''),'') AS offences
   FROM status_history h LEFT JOIN cases c ON c.case_id=h.case_id
   ORDER BY COALESCE(h.event_date,'') DESC,h.case_id LIMIT 20000
  '''),
  'comparisons':rows('SELECT * FROM comparison_cache ORDER BY subject_area,geography,metric,period LIMIT 30000'),
  'prosecution':rows('SELECT * FROM prosecution_statistics ORDER BY fiscal_year DESC LIMIT 10000'),
  'prosecutionReports':rows('SELECT * FROM prosecution_reports ORDER BY report_year DESC LIMIT 1000'),
  'search':rows('SELECT entity_type,entity_id,title,body,source_url FROM justice_search LIMIT 50000') if has_table(c,'justice_search') else [],
  'reviews':rows("SELECT * FROM review_queue WHERE status='open' ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,created_at DESC LIMIT 10000"),
  'documents':rows("SELECT document_id,title,source_type,local_path,published_date,retrieved_at,parse_status,extraction_confidence,notes FROM source_documents WHERE lower(COALESCE(source_type,'')) LIKE '%pdf%' OR lower(COALESCE(local_path,'')) LIKE '%.pdf' ORDER BY retrieved_at DESC LIMIT 10000"),
  'reviewActions':rows('SELECT * FROM review_actions ORDER BY applied_at DESC LIMIT 5000') if has_table(c,'review_actions') else [],
  'repeatOffenders':json.loads((DATA/'repeat-offenders.json').read_text(encoding='utf-8')).get('records',[]) if (DATA/'repeat-offenders.json').exists() else []
 }
 DATA.mkdir(exist_ok=True); (DATA/'advanced-data.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8')

def main():
 parser=argparse.ArgumentParser(description='Build advanced BC Justice Data Hub features.')
 parser.add_argument('--profile',choices=('all','identity','nonidentity'),default='all',help='Run all stages, identity-related stages, or non-identity statistics/governance stages.')
 args=parser.parse_args()
 print('Advanced features: opening database...', flush=True)
 c=sqlite3.connect(DB,timeout=60); c.row_factory=sqlite3.Row
 c.execute('PRAGMA busy_timeout=60000')
 setup(c)
 all_stages=[
  ('Prosecution data',prosecution,'prosecution'),
  ('Duplicate identities',duplicate_people,'duplicates'),
  ('Case timelines',timelines,'timelines'),
  ('Judgment enrichment',enrich_judgments,'judgments'),
  ('Cross-source case links',link_records,'links'),
  ('Privacy safeguards',privacy,'privacy'),
  ('Adult custody extraction',adult_custody,'adultCustody'),
  ('Comparison cache',comparisons,'comparisons'),
  ('Advanced search index',search_index,'search'),
  ('Repeat-offender review',repeat_offenders,'repeatOffenders'),
 ]
 identity_keys={'duplicates','timelines','links','privacy','search','repeatOffenders'}
 if args.profile=='all':
  stages=all_stages
 elif args.profile=='identity':
  stages=[stage for stage in all_stages if stage[2] in identity_keys]
  print('Advanced features: identity profile selected; custody, prosecution, judgment enrichment, and comparison extraction skipped.', flush=True)
 else:
  stages=[stage for stage in all_stages if stage[2] not in identity_keys]
  print('Advanced features: non-identity profile selected; identity candidates, case links, privacy, identity search and repeat-offender stages skipped.', flush=True)
 stats={}
 for label,fn,key in stages:
  print(f'Advanced features: {label}...', flush=True)
  stats[key]=fn(c)
  c.commit()
  print(f'Advanced features: {label} complete ({stats[key]}).', flush=True)
 print('Advanced features: exporting snapshots...', flush=True)
 export(c)
 c.close()
 print(json.dumps(stats,indent=2), flush=True)
 print('Advanced features: complete.', flush=True)
 return 0

if __name__=='__main__': raise SystemExit(main())
