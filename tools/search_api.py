"""Loopback-only SQLite/FTS5 search API for BC Justice Data Hub."""
from __future__ import annotations
import argparse,json,re,sqlite3,threading,time,subprocess,sys,unicodedata
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlparse
ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'database'/'bc_justice.db'
REVIEW_LOCK=threading.Lock();APPEARANCE_LOCK=threading.Lock();WAL_LOCK=threading.Lock();APPEARANCE_SCHEMA_READY=False
PERSON_LOOKUP_CACHE={'signature':None,'records':{}}
WAL_MODE='unknown'

class SearchUnavailableError(RuntimeError):
 pass

def database_busy(exc):
 text=str(exc or '').casefold()
 return isinstance(exc,sqlite3.OperationalError) and any(token in text for token in ('database is locked','database table is locked','database schema is locked','database is busy'))

def database_uri(path):
 return f"file:{Path(path).resolve().as_posix()}?mode=ro"

def connect(read_only=False,timeout=None):
 wait=(5 if read_only else 30) if timeout is None else timeout
 c=sqlite3.connect(database_uri(DB),uri=True,timeout=wait) if read_only else sqlite3.connect(DB,timeout=wait)
 c.row_factory=sqlite3.Row
 c.execute(f'PRAGMA busy_timeout={max(1000,int(wait*1000))}')
 if read_only:
  c.execute('PRAGMA query_only=ON')
  c.execute('PRAGMA read_uncommitted=1')
 return c

def configure_database_concurrency():
 global WAL_MODE
 with WAL_LOCK:
  try:
   with sqlite3.connect(DB,timeout=5) as c:
    c.execute('PRAGMA busy_timeout=5000')
    WAL_MODE=str(c.execute('PRAGMA journal_mode=WAL').fetchone()[0] or '').casefold()
    if WAL_MODE!='wal': raise RuntimeError(f'Unable to enable WAL mode; SQLite returned {WAL_MODE or "unknown"}.')
    c.execute('PRAGMA synchronous=NORMAL')
    c.execute('PRAGMA wal_autocheckpoint=1000')
   return True
  except Exception as exc:
   if database_busy(exc):
    print('[search-api] database busy; WAL configuration will retry in the background')
    return False
   print(f'[search-api] WAL configuration failed: {exc}')
   return False

def connection_is_read_only(c):
 try:return bool(int(c.execute('PRAGMA query_only').fetchone()[0] or 0))
 except Exception:return False
def norm(v): return ' '.join(re.sub(r'[^a-z0-9]+',' ',str(v or '').casefold()).split())
def appearance_norm(v):
 text=unicodedata.normalize('NFKD',str(v or '')).encode('ascii','ignore').decode('ascii').casefold()
 return ' '.join(re.sub(r'[^a-z0-9]+',' ',text).split())
def appearance_file_norm(v): return re.sub(r'[^a-z0-9]+','',str(v or '').casefold())
APPEARANCE_CACHE_SCHEMA='''
CREATE TABLE IF NOT EXISTS appearance_search_records(
 appearance_id TEXT PRIMARY KEY,
 participant_name TEXT NOT NULL DEFAULT '',
 normalized_name TEXT NOT NULL DEFAULT '',
 court_file_number TEXT NOT NULL DEFAULT '',
 normalized_court_file TEXT NOT NULL DEFAULT '',
 courthouse_name TEXT NOT NULL DEFAULT '',
 list_date TEXT NOT NULL DEFAULT '',
 charge_confidence TEXT NOT NULL DEFAULT 'Charge Not Available',
 payload_json TEXT NOT NULL,
 updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS appearance_search_meta(key TEXT PRIMARY KEY,value TEXT);
CREATE INDEX IF NOT EXISTS idx_appearance_search_name ON appearance_search_records(normalized_name);
CREATE INDEX IF NOT EXISTS idx_appearance_search_court ON appearance_search_records(courthouse_name);
CREATE INDEX IF NOT EXISTS idx_appearance_search_date ON appearance_search_records(list_date);
CREATE INDEX IF NOT EXISTS idx_appearance_search_confidence ON appearance_search_records(charge_confidence);
CREATE INDEX IF NOT EXISTS idx_appearance_search_file ON appearance_search_records(normalized_court_file);
'''
def clean_fts_query(value):
 words=[''.join(ch for ch in part.casefold() if ch.isalnum()) for part in str(value or '').split()]; return ' AND '.join(f'"{x}"*' for x in words if x)
def table_exists(c,name):
 return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",(name,)).fetchone())
def appearance_source_files():
 first=ROOT/'data'/'daily-court-lists.json'
 if not first.exists(): return []
 try:
  payload=json.loads(first.read_text(encoding='utf-8'))
  count=max(1,int(payload.get('pageCount',1) or 1))
 except Exception:
  count=1
 return [first,*[ROOT/'data'/f'daily-court-lists-page-{i}.json' for i in range(2,count+1)]]
def appearance_source_stamp():
 files=appearance_source_files()
 return str(max((p.stat().st_mtime_ns for p in files if p.exists()),default=0))
def rebuild_appearance_cache_from_static(c):
 files=appearance_source_files()
 if not files:return 0
 records=[]
 for path in files:
  if not path.exists():continue
  payload=json.loads(path.read_text(encoding='utf-8'))
  records.extend(payload.get('appearances') or [])
 stamp=appearance_source_stamp(); updated=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
 rows=[]
 for index,item in enumerate(records):
  if not str(item.get('participant_name') or '').strip():continue
  appearance_id=str(item.get('appearance_id') or f"static-{index}-{appearance_file_norm(item.get('court_file_number'))}-{appearance_norm(item.get('participant_name'))}-{item.get('list_date','')}")
  rows.append((appearance_id,str(item.get('participant_name') or ''),appearance_norm(item.get('participant_name')),str(item.get('court_file_number') or ''),appearance_file_norm(item.get('court_file_number')),str(item.get('courthouse_name') or ''),str(item.get('list_date') or ''),str(item.get('charge_confidence') or 'Charge Not Available'),json.dumps(item,ensure_ascii=False,separators=(',',':')),updated))
 with c:
  c.execute('DELETE FROM appearance_search_records')
  c.executemany('INSERT OR REPLACE INTO appearance_search_records VALUES(?,?,?,?,?,?,?,?,?,?)',rows)
  c.execute("INSERT OR REPLACE INTO appearance_search_meta(key,value) VALUES('source_stamp',?)",(stamp,))
  c.execute("INSERT OR REPLACE INTO appearance_search_meta(key,value) VALUES('updated_at',?)",(updated,))
 return len(rows)
def ensure_appearance_cache(c):
 global APPEARANCE_SCHEMA_READY
 with APPEARANCE_LOCK:
  read_only=connection_is_read_only(c)
  exists=table_exists(c,'appearance_search_records')
  if read_only:
   if not exists:
    raise SearchUnavailableError('Appearance search index is temporarily unavailable while local exports are being refreshed.')
   return int(c.execute('SELECT COUNT(*) FROM appearance_search_records').fetchone()[0] or 0)
  if not APPEARANCE_SCHEMA_READY or not exists:
   c.executescript(APPEARANCE_CACHE_SCHEMA);APPEARANCE_SCHEMA_READY=True
  source_stamp=appearance_source_stamp()
  row=c.execute("SELECT value FROM appearance_search_meta WHERE key='source_stamp'").fetchone()
  cached_stamp=row[0] if row else ''
  count=int(c.execute('SELECT COUNT(*) FROM appearance_search_records').fetchone()[0] or 0)
  if source_stamp and (count==0 or cached_stamp!=source_stamp):
   try:return rebuild_appearance_cache_from_static(c)
   except Exception as exc:print(f'[search-api] appearance cache rebuild failed: {exc}')
  return count
def appearance_filters(params):
 name=params.get('name',[''])[0].strip(); match=params.get('match',['partial'])[0].strip().lower(); court=params.get('court',[''])[0].strip(); date_from=params.get('from',[''])[0].strip(); date_to=params.get('to',[''])[0].strip(); confidence=params.get('confidence',[''])[0].strip()
 where=[]; args=[]; normalized=appearance_norm(name)
 if normalized:
  if match=='exact':where.append('normalized_name=?');args.append(normalized)
  else:where.append('normalized_name LIKE ?');args.append(f'%{normalized}%')
 if court:where.append('courthouse_name=?');args.append(court)
 if date_from:where.append('list_date>=?');args.append(date_from)
 if date_to:where.append('list_date<=?');args.append(date_to)
 if confidence:where.append('charge_confidence=?');args.append(confidence)
 return where,args
def appearance_person_lookup(c):
 global PERSON_LOOKUP_CACHE
 if not table_exists(c,'search_records'): return {}
 try:
  row=c.execute("SELECT COUNT(*),COALESCE(MAX(indexed_at),'') FROM search_records WHERE entity_type='person'").fetchone()
  signature=(int(row[0] or 0),str(row[1] or ''))
 except sqlite3.Error:
  return {}
 if PERSON_LOOKUP_CACHE.get('signature')==signature:
  return PERSON_LOOKUP_CACHE.get('records') or {}
 lookup={}
 try:
  rows=c.execute("SELECT payload_json FROM search_records WHERE entity_type='person' AND COALESCE(NULLIF(trim(record_status),''),'current')='current'")
  for row in rows:
   try:item=json.loads(row[0])
   except Exception:continue
   person_id=str(item.get('id') or item.get('person_id') or item.get('entity_id') or '').strip()
   if not person_id:continue
   names=[item.get('title'),item.get('display_name'),item.get('name'),*(item.get('names') or []),*(item.get('name_variants') or [])]
   for value in names:
    key=appearance_norm(value)
    if not key:continue
    bucket=lookup.setdefault(key,{})
    bucket[person_id]=item
  lookup={key:list(items.values()) for key,items in lookup.items()}
 except sqlite3.Error:
  lookup={}
 PERSON_LOOKUP_CACHE={'signature':signature,'records':lookup}
 return lookup

def enrich_appearance_people(c,records):
 lookup=appearance_person_lookup(c)
 for item in records:
  matches=lookup.get(appearance_norm(item.get('participant_name')),[])
  item['identity_match_count']=len(matches)
  item['person_profile_id']=str((matches[0].get('id') or matches[0].get('person_id') or matches[0].get('entity_id') or '')) if len(matches)==1 else ''
  item['identity_review_required']=len(matches)!=1
 return records

def search_appearances(c,params):
 ensure_appearance_cache(c); where,args=appearance_filters(params)
 limit=max(1,min(1000,int(params.get('limit',['50'])[0] or 50))); offset=max(0,int(params.get('offset',['0'])[0] or 0)); predicate=(' WHERE '+' AND '.join(where)) if where else ''
 sort=params.get('sort',['newest'])[0].strip().lower() or 'newest'; group=params.get('group',[''])[0].strip().lower()
 confidence_order="CASE r.charge_confidence WHEN 'Confirmed' THEN 1 WHEN 'Likely' THEN 2 WHEN 'Possible' THEN 3 WHEN 'Non Verified' THEN 4 ELSE 5 END"
 newest_order="CASE WHEN trim(r.list_date)='' THEN 1 ELSE 0 END,r.list_date DESC,json_extract(r.payload_json,'$.appearance_time') DESC,r.participant_name COLLATE NOCASE,r.court_file_number COLLATE NOCASE"
 order_by={
  'newest':newest_order,
  'oldest':"CASE WHEN trim(r.list_date)='' THEN 1 ELSE 0 END,r.list_date ASC,json_extract(r.payload_json,'$.appearance_time') ASC,r.participant_name COLLATE NOCASE,r.court_file_number COLLATE NOCASE",
  'name':"r.participant_name COLLATE NOCASE,"+newest_order,
  'courthouse':"CASE WHEN trim(r.courthouse_name)='' THEN 1 ELSE 0 END,r.courthouse_name COLLATE NOCASE,"+newest_order,
  'confidence':confidence_order+","+newest_order,
  'history':"history_count DESC,"+newest_order,
 }.get(sort,newest_order)
 if sort not in {'newest','oldest','name','courthouse','confidence','history'}:sort='newest'
 select_sql="""SELECT r.payload_json,r.normalized_court_file,r.appearance_id,
   (SELECT COUNT(*) FROM appearance_search_records h
      WHERE (r.normalized_name<>'' AND h.normalized_name=r.normalized_name)
         OR (r.normalized_court_file<>'' AND h.normalized_court_file=r.normalized_court_file)) history_count
   FROM appearance_search_records r"""+predicate+' ORDER BY '+order_by
 if group=='file':
  raw=list(c.execute(select_sql,args)); parsed=[]
  for row in raw:
   item=json.loads(row['payload_json']);item['history_count']=int(row['history_count'] or 1);item['_normalized_court_file']=str(row['normalized_court_file'] or '');parsed.append(item)
  enrich_appearance_people(c,parsed)
  grouped={}
  for item in parsed:
   key=('file:'+item['_normalized_court_file']) if item['_normalized_court_file'] else ('appearance:'+str(item.get('appearance_id') or len(grouped)))
   grouped.setdefault(key,[]).append(item)
  groups=[]
  for items in grouped.values():
   primary=dict(items[0]);primary.pop('_normalized_court_file',None)
   for item in items:item.pop('_normalized_court_file',None)
   primary['group_count']=len(items);primary['grouped_appearances']=items
   primary['history_count']=max([int(x.get('history_count') or 1) for x in items] or [1])
   groups.append(primary)
  total=len(groups);page=groups[offset:offset+limit]
  return {'records':page,'total':total,'limit':limit,'offset':offset,'sort':sort,'group':'file','grouped':True,'source':'sqlite-appearance-cache'}
 total=int(c.execute('SELECT COUNT(*) FROM appearance_search_records'+predicate,args).fetchone()[0] or 0)
 rows=[]
 for row in c.execute(select_sql+' LIMIT ? OFFSET ?',[*args,limit,offset]):
  item=json.loads(row['payload_json']);item['history_count']=int(row['history_count'] or 1);rows.append(item)
 enrich_appearance_people(c,rows)
 return {'records':rows,'total':total,'limit':limit,'offset':offset,'sort':sort,'group':'','grouped':False,'source':'sqlite-appearance-cache'}
def appearance_facets(c):
 total=ensure_appearance_cache(c)
 courts=[r[0] for r in c.execute("SELECT DISTINCT courthouse_name FROM appearance_search_records WHERE trim(courthouse_name)<>'' ORDER BY courthouse_name COLLATE NOCASE")]
 return {'courthouses':courts,'catalogueTotal':total,'source':'sqlite-appearance-cache'}
def appearance_history(c,params):
 ensure_appearance_cache(c); appearance_id=params.get('appearanceId',[''])[0].strip()
 if not appearance_id:return {'records':[],'total':0,'source':'sqlite-appearance-cache'}
 current=c.execute('SELECT normalized_name,normalized_court_file FROM appearance_search_records WHERE appearance_id=?',(appearance_id,)).fetchone()
 if not current:return {'records':[],'total':0,'source':'sqlite-appearance-cache'}
 clauses=[];args=[]
 if current['normalized_name']:clauses.append('normalized_name=?');args.append(current['normalized_name'])
 if current['normalized_court_file']:clauses.append('normalized_court_file=?');args.append(current['normalized_court_file'])
 if not clauses:return {'records':[],'total':0,'source':'sqlite-appearance-cache'}
 records=[json.loads(r[0]) for r in c.execute("SELECT payload_json FROM appearance_search_records WHERE "+' OR '.join(clauses)+" ORDER BY list_date DESC,json_extract(payload_json,'$.appearance_time') DESC",args)]
 return {'records':records,'total':len(records),'source':'sqlite-appearance-cache'}
def search_record_count(c):
 if not table_exists(c,'search_records'): return 0
 return int(c.execute('SELECT COUNT(*) FROM search_records').fetchone()[0] or 0)
def rebuild_search_index_if_empty():
 if not DB.exists(): return False
 try:
  with connect() as c:
   if search_record_count(c)>0:return False
  print('[search-api] search index empty; rebuilding dashboard/search exports')
  subprocess.run([sys.executable,str(ROOT/'tools'/'data_pipeline.py'),'export'],cwd=ROOT,check=True)
  return True
 except Exception as exc:
  print(f'[search-api] automatic index rebuild failed: {exc}')
  return False
def status_payload(c):
 meta={}
 if table_exists(c,'search_index_meta'):
  meta={r['key']:r['value'] for r in c.execute('SELECT key,value FROM search_index_meta')}
 db_mtime=datetime.fromtimestamp(DB.stat().st_mtime,timezone.utc).replace(microsecond=0).isoformat() if DB.exists() else ''
 indexed=meta.get('indexed_at',''); actual=search_record_count(c); reported=int(meta.get('record_count','0') or 0); count=actual or reported
 state='empty' if count==0 else ('current' if indexed and indexed>=db_mtime else 'outdated')
 return {'mode':'SQLite + FTS5','databaseUpdatedAt':db_mtime,'indexUpdatedAt':indexed,'recordsIndexed':count,'indexStatus':state,'incrementalChanged':int(meta.get('changed_count','0') or 0),'incrementalRemoved':int(meta.get('removed_count','0') or 0)}
def alias_terms(c,value):
 n=norm(value)
 if not n:return []
 try:
  row=c.execute('SELECT canonical_normalized FROM courthouse_aliases WHERE alias_normalized=?',(n,)).fetchone(); canonical=row[0] if row else n
  return sorted({r[0] for r in c.execute('SELECT alias_name FROM courthouse_aliases WHERE canonical_normalized=?',(canonical,))}|{value})
 except sqlite3.OperationalError:return [value]
def matter_key(r):
 file=norm(r.get('court_file_normalized') or r.get('court_file')); citation=norm(r.get('citation')); location=norm(r.get('location') or r.get('court'))
 if file:return f'file:{file}:{location}'
 if citation:return f'citation:{citation}'
 if r.get('case_id'):return f"case:{r['case_id']}"
 return f"record:{r.get('type')}:{r.get('id')}"
def group_records(records):
 groups={}
 for r in records:
  k=matter_key(r); g=groups.setdefault(k,{'grouped':True,'matter_key':k,'title':r.get('court_file') or r.get('citation') or r.get('title') or 'Linked matter','records':[],'types':set(),'latest_date':'','verification':'unknown'})
  g['records'].append(r); g['types'].add(r.get('type','record')); g['latest_date']=max(g['latest_date'],str(r.get('date') or ''))
  if r.get('verification') in ('verified','official','reviewed'):g['verification']=r.get('verification')
 out=[]
 for g in groups.values():
  if len(g['records'])==1: out.append(g['records'][0]); continue
  g['types']=sorted(g['types']); g['counts']={t:sum(1 for r in g['records'] if r.get('type')==t) for t in g['types']}; g['records']=sorted(g['records'],key=lambda r:str(r.get('date') or ''),reverse=True); out.append(g)
 return sorted(out,key=lambda x:str(x.get('latest_date') or x.get('date') or ''),reverse=True)
def search(c, params):
 q=params.get('q',[''])[0].strip(); typ=params.get('type',[''])[0].strip(); types=[x.strip() for x in params.get('types',[''])[0].split(',') if x.strip()]; offence=params.get('offence',[''])[0].strip(); court=params.get('court',[''])[0].strip(); outcome=params.get('outcome',[''])[0].strip(); verification=params.get('verification',[''])[0].strip(); date_from=params.get('dateFrom',[''])[0].strip(); date_to=params.get('dateTo',[''])[0].strip(); record_status=params.get('recordStatus',['current'])[0].strip() or 'current'; group=params.get('group',['true'])[0].lower()!='false'
 metric=params.get('metric',[''])[0].strip(); dataset=params.get('dataset',[''])[0].strip(); geography=params.get('geography',[''])[0].strip(); period=params.get('period',[''])[0].strip(); unit=params.get('unit',[''])[0].strip()
 limit=max(1,min(100,int(params.get('limit',['25'])[0] or 25))); offset=max(0,int(params.get('offset',['0'])[0] or 0)); where=[]; args=[]
 if typ:where.append('r.entity_type=?');args.append(typ)
 if not typ and types:
  marks=','.join('?' for _ in types);where.append(f'r.entity_type IN ({marks})');args.extend(types)
 if offence:where.append('r.offences LIKE ?');args.append(f'%{offence}%')
 if court:
  terms=alias_terms(c,court); bits=[]
  for term in terms:bits.append('(r.court LIKE ? OR r.location LIKE ?)');args.extend([f'%{term}%',f'%{term}%'])
  where.append('('+ ' OR '.join(bits)+')')
 if outcome:where.append('r.outcome LIKE ?');args.append(f'%{outcome}%')
 if verification:where.append('r.verification=?');args.append(verification)
 if date_from:where.append("substr(r.record_date,1,10)>=?");args.append(date_from)
 if date_to:where.append("substr(r.record_date,1,10)<=?");args.append(date_to)
 if record_status!='all':where.append("COALESCE(NULLIF(trim(r.record_status),''),'current')=?");args.append(record_status)
 for key,val,paths in [('metric',metric,['$.metric']),('dataset',dataset,['$.dataset_id','$.domain']),('geography',geography,['$.location']),('period',period,['$.date']),('unit',unit,['$.unit'])]:
  if val:where.append('('+ ' OR '.join("json_extract(r.payload_json,?) LIKE ?" for _ in paths)+')'); [args.extend([path,f'%{val}%']) for path in paths]
 pred=(' AND '+' AND '.join(where)) if where else ''; fts=clean_fts_query(q)
 should_group=group and typ!='statistics' and 'statistics' not in types

 def query_rows(base, query_args, order_by, rank_expression='0 rank'):
  if should_group:
   return list(c.execute(f'SELECT r.payload_json,r.indexed_at,{rank_expression} {base} {order_by}',query_args)),None
  total=int(c.execute('SELECT COUNT(*) '+base,query_args).fetchone()[0])
  rows=list(c.execute(f'SELECT r.payload_json,r.indexed_at,{rank_expression} {base} {order_by} LIMIT ? OFFSET ?',[*query_args,limit,offset]))
  return rows,total

 raw=[]; total=None; used_fts=False
 if fts and table_exists(c,'search_fts'):
  try:
   base='FROM search_fts f JOIN search_records r ON r.record_id=f.record_id WHERE search_fts MATCH ?'+pred
   raw,total=query_rows(base,[fts,*args],'ORDER BY rank ASC,r.record_date DESC','bm25(search_fts,0,8,7,10,4,3,2,2,2,2,1) rank')
   used_fts=True
  except sqlite3.OperationalError as exc:
   print(f'[search-api] FTS query failed; using direct search: {exc}')
 if fts and (not used_fts or (total==0 if total is not None else not raw)):
  tokens=[norm(x) for x in q.split() if norm(x)]
  direct=[]; direct_args=[]
  for token in tokens:
   direct.append("(lower(r.title) LIKE ? OR lower(r.names) LIKE ? OR lower(r.court_file_number) LIKE ? OR lower(r.payload_json) LIKE ?)")
   like=f'%{token}%'; direct_args.extend([like,like,like,like])
  direct_pred=(' AND '+' AND '.join(direct)) if direct else ''
  base='FROM search_records r WHERE 1=1'+pred+direct_pred
  raw,total=query_rows(base,[*args,*direct_args],'ORDER BY r.record_date DESC,r.title')
 elif not fts:
  base='FROM search_records r WHERE 1=1'+pred
  raw,total=query_rows(base,args,'ORDER BY r.record_date DESC,r.title')
 records=[]
 for row in raw:
  item=json.loads(row['payload_json']); item['indexed_at']=row['indexed_at']; records.append(item)
 if not should_group:
  return {'records':records,'total':int(total or 0),'limit':limit,'offset':offset,'source':'sqlite-fts5','grouped':False}
 results=group_records(records); total=len(results); page=results[offset:offset+limit]
 return {'records':page,'total':total,'limit':limit,'offset':offset,'source':'sqlite-fts5','grouped':True}

LAST_ACTIVITY=time.monotonic()
IDLE_TIMEOUT=300

class Handler(BaseHTTPRequestHandler):
 server_version='BCJUSSearch/0.20.2'
 def end_headers(self):
  self.send_header('Access-Control-Allow-Origin','*')
  self.send_header('Access-Control-Allow-Headers','Content-Type')
  self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS')
  super().end_headers()
 def do_OPTIONS(self):
  self.send_response(204); self.end_headers()
 def read_json(self):
  size=int(self.headers.get('Content-Length','0') or 0)
  if size<=0 or size>65536: raise ValueError('Invalid request size')
  return json.loads(self.rfile.read(size).decode('utf-8'))
 def apply_review_action(self,action):
  action_type=(action.get('action_type') or '').strip()
  decision=(action.get('decision') or '').strip().lower()
  allowed={
   'judgment_review':{'verify','dismiss','needs_correction'},
   'review':{'resolve','dismiss'},
   'pdf_correction':{'approve','note'},
  }
  if action_type not in allowed or decision not in allowed[action_type]:
   raise ValueError('Unsupported automatic review action')
  from apply_review_actions import setup,apply
  with REVIEW_LOCK:
   subprocess.run([sys.executable,str(ROOT/'tools'/'workflow_cache.py'),'snapshot','auto-review-db',str(DB)],cwd=ROOT,check=True)
   with connect() as c:
    setup(c)
    with c: apply(c,action)
   commands=[]
   if action_type=='judgment_review' and decision=='verify':
    commands.extend(([sys.executable,str(ROOT/'tools'/'collect_justice_sources.py'),'export'],[sys.executable,str(ROOT/'tools'/'advanced_features.py')]))
   commands.append([sys.executable,str(ROOT/'tools'/'data_pipeline.py'),'export'])
   for command in commands: subprocess.run(command,cwd=ROOT,check=True)
  return {'ok':True,'applied':True,'entity_id':action.get('entity_id'),'target_entity_id':action.get('target_entity_id'),'decision':decision}
 def restore_review(self,payload):
  archive_id=int(payload.get('archive_id') or 0)
  if archive_id<=0: raise ValueError('Invalid archive id')
  with REVIEW_LOCK:
   subprocess.run([sys.executable,str(ROOT/'tools'/'workflow_cache.py'),'snapshot','restore-review-db',str(DB)],cwd=ROOT,check=True)
   with connect() as c:
    row=c.execute('SELECT * FROM dismissed_review_archive WHERE archive_id=?',(archive_id,)).fetchone()
    if not row: raise ValueError('Archived review not found')
    item=dict(row)
    with c:
     c.execute('DELETE FROM dismissed_review_archive WHERE archive_id=?',(archive_id,))
     c.execute("INSERT OR REPLACE INTO review_queue(review_id,entity_type,entity_id,reason,severity,source_document_id,status,created_at,resolved_at,resolution_notes) VALUES(?,?,?,?,?,?, 'open', ?,NULL,NULL)",(item.get('review_id'),item.get('entity_type'),item.get('entity_id'),item.get('reason'),item.get('severity') or 'medium',item.get('source_document_id'),item.get('original_created_at') or datetime.now(timezone.utc).replace(microsecond=0).isoformat()))
   # Rebuild all review-facing exports before replying so every page and count
   # sees the restored item immediately.
   subprocess.run([sys.executable,str(ROOT/'tools'/'advanced_features.py')],cwd=ROOT,check=True)
   subprocess.run([sys.executable,str(ROOT/'tools'/'data_pipeline.py'),'export'],cwd=ROOT,check=True)
   with connect() as c:
    active_count=c.execute("SELECT COUNT(*) FROM review_queue WHERE status='open'").fetchone()[0]
    archive_count=c.execute('SELECT COUNT(*) FROM dismissed_review_archive').fetchone()[0]
  return {'ok':True,'restored':True,'archive_id':archive_id,'review_id':item.get('review_id'),'review':{
   'review_id':item.get('review_id'),'entity_type':item.get('entity_type'),'entity_id':item.get('entity_id'),
   'reason':item.get('reason'),'severity':item.get('severity') or 'medium','source_document_id':item.get('source_document_id'),
   'created_at':item.get('original_created_at'),'status':'open'
  },'active_review_count':active_count,'dismissed_review_count':archive_count}
 def do_POST(self):
  global LAST_ACTIVITY
  LAST_ACTIVITY=time.monotonic(); parsed=urlparse(self.path)
  try:
   if parsed.path=='/api/reviews/apply': return self.send_json(self.apply_review_action(self.read_json()))
   if parsed.path=='/api/reviews/restore': return self.send_json(self.restore_review(self.read_json()))
   return self.send_json({'error':'Not found'},404)
  except Exception as exc:
   if database_busy(exc):return self.send_database_busy()
   return self.send_json({'error':str(exc)},400)
 def send_json(self,payload,code=200,headers=None):
  raw=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode(); self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store')
  for name,value in (headers or {}).items():self.send_header(name,str(value))
  self.end_headers(); self.wfile.write(raw)
 def send_database_busy(self,message='Search database is temporarily busy while local collection or maintenance is writing. Retry shortly.'):
  return self.send_json({'error':message,'code':'database_busy','retryable':True,'retryAfterSeconds':2},503,{'Retry-After':'2'})
 def do_GET(self):
  global LAST_ACTIVITY
  LAST_ACTIVITY=time.monotonic()
  parsed=urlparse(self.path)
  if parsed.path=='/api/heartbeat':return self.send_json({'ok':True,'idleTimeoutSeconds':IDLE_TIMEOUT,'databaseReady':None})
  try:
   with connect(read_only=True) as c:
    if parsed.path=='/api/appearances':return self.send_json(search_appearances(c,parse_qs(parsed.query)))
    if parsed.path=='/api/appearances/facets':return self.send_json(appearance_facets(c))
    if parsed.path=='/api/appearances/history':return self.send_json(appearance_history(c,parse_qs(parsed.query)))
    if parsed.path=='/api/search':return self.send_json(search(c,parse_qs(parsed.query)))
    if parsed.path=='/api/search/status':
     payload=status_payload(c);payload['journalMode']=str(c.execute('PRAGMA journal_mode').fetchone()[0] or WAL_MODE);payload['readOnly']=True
     return self.send_json(payload)
    if parsed.path=='/api/courts':
     try:rows=c.execute('SELECT alias_name,canonical_name,source FROM courthouse_aliases ORDER BY canonical_name,alias_name'); return self.send_json({'aliases':[dict(r) for r in rows]})
     except sqlite3.OperationalError as exc:
      if database_busy(exc):raise
      return self.send_json({'aliases':[]})
    if parsed.path=='/api/search/facets':
     facet={}
     for name,path in [('metrics','$.metric'),('datasets','$.dataset_id'),('domains','$.domain'),('geographies','$.location'),('periods','$.date'),('units','$.unit')]: facet[name]=[r[0] for r in c.execute("SELECT DISTINCT json_extract(payload_json,?) v FROM search_records WHERE entity_type='statistics' AND v IS NOT NULL AND v!='' ORDER BY v LIMIT 500",(path,))]
     return self.send_json(facet)
   return self.send_json({'error':'Not found'},404)
  except SearchUnavailableError as exc:return self.send_json({'error':str(exc),'code':'search_index_unavailable','retryable':True,'retryAfterSeconds':2},503,{'Retry-After':'2'})
  except Exception as exc:
   if database_busy(exc):return self.send_database_busy()
   return self.send_json({'error':str(exc)},500)
 def log_message(self,fmt,*args):print('[search-api]',fmt%args)
def main():
 global IDLE_TIMEOUT,LAST_ACTIVITY
 ap=argparse.ArgumentParser();ap.add_argument('--host',default='127.0.0.1');ap.add_argument('--port',type=int,default=8765);ap.add_argument('--idle-timeout',type=int,default=300);a=ap.parse_args()
 IDLE_TIMEOUT=max(60,a.idle_timeout);LAST_ACTIVITY=time.monotonic()
 if not DB.exists():raise SystemExit(f'Database not found: {DB}. Run tools\\setup-data.cmd first.')
 wal_ready=configure_database_concurrency()
 server=ThreadingHTTPServer((a.host,a.port),Handler)
 def idle_watch():
  while True:
   time.sleep(5)
   if time.monotonic()-LAST_ACTIVITY>=IDLE_TIMEOUT:
    print(f'[search-api] idle for {IDLE_TIMEOUT} seconds; stopping')
    server.shutdown();return
 def wal_watch():
  nonlocal wal_ready
  while not wal_ready:
   time.sleep(5);wal_ready=configure_database_concurrency()
 threading.Thread(target=idle_watch,daemon=True).start()
 if not wal_ready:threading.Thread(target=wal_watch,daemon=True).start()
 print(f'BCJUS local search API: http://{a.host}:{a.port} (idle timeout {IDLE_TIMEOUT}s; read-only requests; WAL {"ready" if wal_ready else "pending"})')
 server.serve_forever();server.server_close()
if __name__=='__main__':main()
