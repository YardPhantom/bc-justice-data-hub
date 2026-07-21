#!/usr/bin/env python3
"""BC Justice Data Hub local ingestion and export pipeline.

Commands:
  setup                  Create/migrate the SQLite schema.
  import                 Import downloaded/locally supplied resources.
  export                 Regenerate static JSON snapshots used by IIS.
  all                    Setup, import, and export.
  queue FILE [...]       Register local HTML/PDF/CSV/Excel/JSON files.

The pipeline never infers a final criminal outcome from an appearance, charge,
or unstructured source. Such records enter the review queue.
"""
from __future__ import annotations
import argparse, csv, hashlib, io, json, re, sqlite3, sys, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from export_utils import write_json_atomic
from person_mentions import ensure_schema as ensure_person_mentions_schema, rebuild_from_normalized_sources, collection_metrics

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'database'/'bc_justice.db'
DATA=ROOT/'data'
IMPORTS=ROOT/'imports'
POLICY=DATA/'collection-policy.json'
FINAL_STATUSES={'convicted','acquitted','stayed','withdrawn','dismissed'}

SCHEMA='''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS source_documents(
 document_id TEXT PRIMARY KEY, resource_id TEXT, dataset_id TEXT, source_type TEXT,
 title TEXT, source_url TEXT, local_path TEXT, published_date TEXT, retrieved_at TEXT,
 sha256 TEXT, parse_status TEXT DEFAULT 'pending', extraction_confidence REAL,
 page_count INTEGER, raw_metadata TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS import_runs(
 run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
 status TEXT NOT NULL, resource_id TEXT, local_path TEXT, row_count INTEGER DEFAULT 0,
 table_name TEXT, error_text TEXT
);
CREATE TABLE IF NOT EXISTS staging_rows(
 staging_id INTEGER PRIMARY KEY AUTOINCREMENT, resource_id TEXT, dataset_id TEXT,
 source_document_id TEXT, row_number INTEGER, courthouse_slug TEXT, raw_json TEXT NOT NULL,
 imported_at TEXT NOT NULL, row_hash TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS people(
 person_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, normalized_name TEXT,
 date_of_birth TEXT, identity_confidence REAL DEFAULT 0, review_required INTEGER DEFAULT 1,
 created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS cases(
 case_id TEXT PRIMARY KEY, court_file_number TEXT, citation TEXT, court_level TEXT,
 courthouse_slug TEXT, case_title TEXT, opened_date TEXT, closed_date TEXT,
 legal_status TEXT DEFAULT 'unknown', final_outcome TEXT, outcome_date TEXT,
 verification_state TEXT DEFAULT 'review', publication_restriction INTEGER DEFAULT 0,
 source_document_id TEXT, source_url TEXT, retrieved_at TEXT, notes TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_case_file_court ON cases(court_file_number,courthouse_slug) WHERE court_file_number IS NOT NULL AND court_file_number!='';
CREATE TABLE IF NOT EXISTS case_people(
 case_id TEXT, person_id TEXT, role TEXT DEFAULT 'accused', PRIMARY KEY(case_id,person_id,role),
 FOREIGN KEY(case_id) REFERENCES cases(case_id), FOREIGN KEY(person_id) REFERENCES people(person_id)
);
CREATE TABLE IF NOT EXISTS charges(
 charge_id TEXT PRIMARY KEY, case_id TEXT, offence_text TEXT, statute TEXT, section TEXT,
 charge_date TEXT, charge_status TEXT DEFAULT 'alleged', disposition TEXT,
 disposition_date TEXT, source_document_id TEXT
);
CREATE TABLE IF NOT EXISTS case_events(
 event_id TEXT PRIMARY KEY, case_id TEXT, event_type TEXT, event_date TEXT, courtroom TEXT,
 courthouse_slug TEXT, description TEXT, source_document_id TEXT,
 verification_state TEXT DEFAULT 'review'
);
CREATE TABLE IF NOT EXISTS outcomes(
 outcome_id TEXT PRIMARY KEY, case_id TEXT, outcome_type TEXT NOT NULL, outcome_date TEXT,
 sentence_text TEXT, appeal_status TEXT, source_document_id TEXT,
 verified INTEGER DEFAULT 0, verified_at TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS court_statistics(
 stat_id TEXT PRIMARY KEY, courthouse_slug TEXT, region TEXT, fiscal_year TEXT, metric TEXT,
 value REAL, unit TEXT, category TEXT, dataset_id TEXT, resource_id TEXT,
 source_document_id TEXT, raw_json TEXT
);
CREATE TABLE IF NOT EXISTS crime_statistics(
 stat_id TEXT PRIMARY KEY, geography TEXT, year TEXT, offence_category TEXT, metric TEXT,
 value REAL, unit TEXT, dataset_id TEXT, resource_id TEXT, raw_json TEXT
);
CREATE TABLE IF NOT EXISTS prosecution_statistics(
 stat_id TEXT PRIMARY KEY, region TEXT, fiscal_year TEXT, metric TEXT, value REAL,
 unit TEXT, dataset_id TEXT, resource_id TEXT, raw_json TEXT
);
CREATE TABLE IF NOT EXISTS custody_statistics(
 stat_id TEXT PRIMARY KEY, facility TEXT, region TEXT, period TEXT, metric TEXT, value REAL,
 unit TEXT, dataset_id TEXT, resource_id TEXT, raw_json TEXT
);
CREATE TABLE IF NOT EXISTS youth_justice_statistics(
 stat_id TEXT PRIMARY KEY, geography TEXT, period TEXT, service_area TEXT, demographic TEXT,
 metric TEXT, value REAL, unit TEXT, dataset_id TEXT, resource_id TEXT, raw_json TEXT
);
CREATE TABLE IF NOT EXISTS civil_forfeiture_statistics(
 stat_id TEXT PRIMARY KEY, geography TEXT, period TEXT, proceeding_type TEXT, asset_category TEXT,
 metric TEXT, value REAL, unit TEXT, dataset_id TEXT, resource_id TEXT, raw_json TEXT
);
CREATE TABLE IF NOT EXISTS policing_statistics(
 stat_id TEXT PRIMARY KEY, geography TEXT, year TEXT, police_service TEXT, subject_area TEXT,
 metric TEXT, value REAL, unit TEXT, dataset_id TEXT, resource_id TEXT, raw_json TEXT
);
CREATE TABLE IF NOT EXISTS review_queue(
 review_id TEXT PRIMARY KEY, entity_type TEXT, entity_id TEXT, reason TEXT, severity TEXT DEFAULT 'medium',
 source_document_id TEXT, status TEXT DEFAULT 'open', created_at TEXT, resolved_at TEXT, resolution_notes TEXT
);
CREATE TABLE IF NOT EXISTS dismissed_review_archive(
 archive_id INTEGER PRIMARY KEY AUTOINCREMENT, review_id TEXT, entity_type TEXT, entity_id TEXT, reason TEXT, severity TEXT,
 source_document_id TEXT, original_created_at TEXT, dismissed_at TEXT NOT NULL, dismissal_notes TEXT, action_json TEXT,
 UNIQUE(review_id), UNIQUE(entity_type,entity_id,reason)
);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_queue(status,severity);
CREATE INDEX IF NOT EXISTS idx_dismissed_review_entity ON dismissed_review_archive(entity_type,entity_id);
CREATE TRIGGER IF NOT EXISTS prevent_dismissed_review_requeue
BEFORE INSERT ON review_queue
WHEN EXISTS(
 SELECT 1 FROM dismissed_review_archive d
 WHERE d.review_id=NEW.review_id
    OR (COALESCE(d.entity_type,'')=COALESCE(NEW.entity_type,'')
        AND COALESCE(d.entity_id,'')=COALESCE(NEW.entity_id,'')
        AND COALESCE(d.reason,'')=COALESCE(NEW.reason,''))
)
BEGIN SELECT RAISE(IGNORE); END;
CREATE INDEX IF NOT EXISTS idx_staging_resource ON staging_rows(resource_id);
CREATE INDEX IF NOT EXISTS idx_cases_court ON cases(courthouse_slug);
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
 record_id UNINDEXED, entity_type UNINDEXED, title, names, court_file_number,
 offences, outcome, sentence, courthouse, city, source_text,
 tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS search_records(
 record_id TEXT PRIMARY KEY, entity_type TEXT, title TEXT, names TEXT, court_file_number TEXT,
 offences TEXT, outcome TEXT, sentence TEXT, court TEXT, location TEXT, record_date TEXT,
 verification TEXT, record_status TEXT DEFAULT 'current', content_hash TEXT, payload_json TEXT,
 indexed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_search_records_filters ON search_records(entity_type,record_status,verification,record_date);
CREATE INDEX IF NOT EXISTS idx_search_records_location ON search_records(location,court);
CREATE TABLE IF NOT EXISTS search_index_meta(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS courthouse_aliases(
 alias_normalized TEXT PRIMARY KEY, alias_name TEXT NOT NULL, canonical_name TEXT NOT NULL,
 canonical_normalized TEXT NOT NULL, source TEXT DEFAULT 'indexed', updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_courthouse_alias_canonical ON courthouse_aliases(canonical_normalized);


'''

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def sha_bytes(b:bytes): return hashlib.sha256(b).hexdigest()
def text_lower(value): return str(value or '').lower()
def key_lower(value): return text_lower(value)
def slug(s:str): return re.sub(r'-+','-',re.sub(r'[^a-z0-9]+','-',text_lower(s))).strip('-')
def normalize_search(value):
 text=str(value or '').casefold()
 text=re.sub(r'[^a-z0-9]+',' ',text)
 return ' '.join(text.split())
def normalize_file_number(value): return re.sub(r'[^a-z0-9]','',str(value or '').casefold())
def name_variants(value):
 name=' '.join(str(value or '').split())
 if not name: return []
 variants={name,name.casefold()}
 if ',' in name:
  last,first=[x.strip() for x in name.split(',',1)]
  if first and last: variants.add(f'{first} {last}')
 else:
  bits=name.split()
  if len(bits)>1: variants.add(f'{bits[-1]}, {' '.join(bits[:-1])}')
 return sorted(variants)
def connect():
 DB.parent.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def columns(c,table): return {r[1] for r in c.execute(f'PRAGMA table_info({table})')}
def add_column(c,table,spec):
 name=spec.split()[0]
 if name not in columns(c,table): c.execute(f'ALTER TABLE {table} ADD COLUMN {spec}')

def setup(c):
 c.executescript(SCHEMA)
 ensure_person_mentions_schema(c)
 # Migrate catalogue tables from v0.1.1 without destructive recreation.
 if 'catalogue_datasets' in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
  for spec in ['collection_state TEXT DEFAULT \'review\'','priority INTEGER DEFAULT 50','selected_at TEXT','import_notes TEXT']:
   add_column(c,'catalogue_datasets',spec)
 if 'catalogue_resources' in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
  for spec in ["collection_state TEXT DEFAULT 'review'","import_state TEXT DEFAULT 'not_imported'",'import_error TEXT','imported_at TEXT','row_count INTEGER DEFAULT 0','table_name TEXT']:
   add_column(c,'catalogue_resources',spec)
 c.commit()

def load_policy():
 default={"auto_enable_formats":["CSV","XLS","XLSX","JSON","API"],"document_formats":["PDF","HTML"],"ignored_formats":["WMS","KML"],"max_download_mb":100,"dataset_overrides":{},"resource_overrides":{}}
 if POLICY.exists():
  try: default.update(json.loads(POLICY.read_text(encoding='utf-8')))
  except Exception: pass
 return default

def iter_csv(path):
 raw=path.read_bytes(); text=None
 for enc in ('utf-8-sig','utf-8','cp1252','latin1'):
  try: text=raw.decode(enc); break
  except UnicodeDecodeError: pass
 if text is None: raise ValueError('Unable to decode CSV')

 # Detect the delimiter once, but do not trust the source to be valid RFC CSV.
 sample=text[:8192]
 try: dialect=csv.Sniffer().sniff(sample,delimiters=',;\t|')
 except csv.Error: dialect=csv.excel

 def normal_reader(value):
  stream=io.StringIO(value,newline='')
  return csv.DictReader(stream,dialect=dialect)

 def parse_record(value):
  # Parse one reconstructed logical record. strict=False tolerates imperfect
  # quoting found in several BC Catalogue CSV exports.
  return next(csv.reader(io.StringIO(value,newline=''),dialect=dialect,strict=False))

 def repaired_rows(value):
  # Last-resort parser for exports containing literal, unquoted line breaks in
  # field values. Reconstruct physical lines until they contain the header's
  # expected number of columns, then return a stable dictionary.
  physical=value.replace('\r\n','\n').replace('\r','\n').split('\n')
  while physical and not physical[0].strip(): physical.pop(0)
  if not physical: return
  header=parse_record(physical.pop(0))
  header=[str(h or '').strip() or f'column_{i+1}' for i,h in enumerate(header)]
  expected=len(header)
  pending=''
  for line in physical:
   pending = f'{pending} {line}'.strip() if pending else line
   try: fields=parse_record(pending)
   except (csv.Error, StopIteration):
    continue
   if len(fields) < expected:
    continue
   if len(fields) > expected:
    # Preserve all content instead of dropping overflow caused by malformed
    # delimiters; attach it to the final field for manual review.
    fields=fields[:expected-1]+[dialect.delimiter.join(fields[expected-1:])]
   yield dict(zip(header,fields))
   pending=''
  if pending.strip():
   try: fields=parse_record(pending)
   except (csv.Error, StopIteration): fields=[pending]
   fields=(fields+['']*expected)[:expected]
   yield dict(zip(header,fields))

 try:
  # Materialize before yielding so a late parser exception cannot leave a
  # resource half-imported before the fallback starts.
  rows=list(normal_reader(text))
 except csv.Error:
  normalized=text.replace('\r\n','\n').replace('\r','\n')
  try: rows=list(normal_reader(normalized))
  except csv.Error: rows=list(repaired_rows(normalized))
 yield from rows


def normalize_row(row):
 # csv.DictReader uses a None key when a physical row has more fields than
 # the header. Convert every key to stable text and preserve overflow values
 # under a named column so hashing/sorting can never compare None with str.
 clean={}
 overflow=[]
 for index,(key,value) in enumerate((row or {}).items(),1):
  if key is None:
   if isinstance(value,list): overflow.extend(value)
   elif value not in (None,''): overflow.append(value)
   continue
  name=str(key).strip() or f'column_{index}'
  if name in clean:
   suffix=2
   while f'{name}_{suffix}' in clean: suffix+=1
   name=f'{name}_{suffix}'
  clean[name]=value
 if overflow:
  clean['_overflow']=' | '.join(str(v) for v in overflow if v not in (None,''))
 return clean

def iter_json(path):
 data=json.loads(path.read_text(encoding='utf-8-sig'))
 if isinstance(data,list): yield from data
 elif isinstance(data,dict):
  for key in ('results','result','records','data','features'):
   if isinstance(data.get(key),list):
    for item in data[key]:
     if key=='features' and isinstance(item,dict): yield {**(item.get('properties') or {}),'geometry':item.get('geometry')}
     else: yield item
    return
  yield data
 else: yield {'value':data}

def iter_excel(path):
 suffix=path.suffix.lower()
 # BC Catalogue resources are occasionally mislabeled. Detect the actual
 # workbook container instead of trusting only the filename extension.
 with path.open('rb') as workbook_file:
  signature=workbook_file.read(8)
 is_openxml=signature.startswith(b'PK\x03\x04')
 is_legacy_ole=signature.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1')

 if suffix=='.xls' and not is_openxml:
  try: import xlrd
  except ImportError as e:
   raise RuntimeError('Legacy .xls import requires: py -m pip install xlrd') from e
  try:
   wb=xlrd.open_workbook(path, on_demand=True)
  except Exception as e:
   kind='legacy OLE workbook' if is_legacy_ole else 'file labeled .xls'
   raise RuntimeError(f'Unable to read {kind}: {e}') from e
  try:
   for ws in wb.sheets():
    if ws.nrows < 1: continue
    headers=[str(x or f'column_{i+1}').strip() for i,x in enumerate(ws.row_values(0))]
    for row_index in range(1,ws.nrows):
     row=ws.row_values(row_index)
     yield {'_sheet':ws.name,**{headers[i]:row[i] if i<len(row) else None for i in range(len(headers))}}
  finally:
   wb.release_resources()
  return

 try: import openpyxl
 except ImportError as e: raise RuntimeError('Modern Excel import requires: py -m pip install openpyxl') from e
 try:
  # Passing a binary stream lets openpyxl read Open XML workbooks even when
  # the Catalogue gave them an incorrect .xls filename.
  with path.open('rb') as workbook_file:
   wb=openpyxl.load_workbook(workbook_file,read_only=True,data_only=True)
   for ws in wb.worksheets:
    rows=ws.iter_rows(values_only=True)
    try: headers=[str(x or f'column_{i+1}').strip() for i,x in enumerate(next(rows))]
    except StopIteration: continue
    for row in rows: yield {'_sheet':ws.title,**{headers[i]:row[i] if i<len(row) else None for i in range(len(headers))}}
 except Exception as e:
  raise RuntimeError(f'Unable to read modern Excel workbook: {e}') from e

def row_iter(path,fmt):
 if fmt=='CSV': return iter_csv(path)
 if fmt=='JSON': return iter_json(path)
 if fmt in {'XLSX','XLS'}: return iter_excel(path)
 raise ValueError(f'No row importer for {fmt}')

def courthouse_match(row,courts):
 text=' '.join(str(v or '') for k,v in row.items() if any(t in key_lower(k) for t in ('court','location','city','registry','geography'))).lower()
 best=''
 for c in courts:
  names={text_lower(c.get('name')),text_lower(c.get('city')),text_lower(c.get('slug')).replace('-',' ')}
  if any(n and n in text for n in names): best=c['slug']; break
 return best

def classify_table(title,headers):
 t=(text_lower(title)+' '+' '.join(str(h or '') for h in headers)).lower()
 if any(x in t for x in ('civil forfeiture','possessory interest','forfeiture office grant')): return 'civil_forfeiture_statistics'
 if any(x in t for x in ('youth custody','youth justice','young offender','separate confinement youth')): return 'youth_justice_statistics'
 if any(x in t for x in ('police strength','police spending','use of force','conducted energy','police dog','firearm discharge','calls for service')): return 'policing_statistics'
 if any(x in t for x in ('custody','correction','remand','admission','release','separate confinement')): return 'custody_statistics'
 if any(x in t for x in ('prosecution','crown counsel','charge approval')): return 'prosecution_statistics'
 if any(x in t for x in ('crime','offence','police','severity index')): return 'crime_statistics'
 if any(x in t for x in ('court','case','trial','disposition')): return 'court_statistics'
 return 'staging_rows'

def numeric(v):
 if v is None:return None
 try:return float(str(v).replace(',','').replace('%','').replace('$','').strip())
 except:return None

def first(row,*needles):
 for k,v in row.items():
  lk=key_lower(k).replace('_',' ')
  if any(n in lk for n in needles) and v not in (None,''): return str(v)
 return ''

def insert_stat(c,table,row,dsid,rid,docid,court):
 metric=first(row,'metric','measure','indicator','statistic','category') or 'Imported value'
 value=None
 for k,v in row.items():
  if any(x in key_lower(k) for x in ('value','count','rate','total','number','percent')):
   value=numeric(v)
   if value is not None: break
 if value is None:return False
 sid=str(uuid.uuid5(uuid.NAMESPACE_URL,rid+json.dumps(row,sort_keys=True,default=str)))
 raw=json.dumps(row,ensure_ascii=False,default=str)
 if table=='court_statistics':
  c.execute('INSERT OR IGNORE INTO court_statistics VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(sid,court,first(row,'region','geography'),first(row,'fiscal','year','period'),metric,value,first(row,'unit'),first(row,'category','division'),dsid,rid,docid,raw))
 elif table=='crime_statistics':
  c.execute('INSERT OR IGNORE INTO crime_statistics VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,first(row,'geography','location','region','municipality'),first(row,'year','period'),first(row,'offence','category'),metric,value,first(row,'unit'),dsid,rid,raw))
 elif table=='prosecution_statistics':
  c.execute('INSERT OR IGNORE INTO prosecution_statistics VALUES(?,?,?,?,?,?,?,?,?)',(sid,first(row,'region','geography'),first(row,'fiscal','year','period'),metric,value,first(row,'unit'),dsid,rid,raw))
 elif table=='custody_statistics':
  c.execute('INSERT OR IGNORE INTO custody_statistics VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,first(row,'facility','centre','institution'),first(row,'region','geography'),first(row,'period','year','date'),metric,value,first(row,'unit'),dsid,rid,raw))
 elif table=='youth_justice_statistics':
  c.execute('INSERT OR IGNORE INTO youth_justice_statistics VALUES(?,?,?,?,?,?,?,?,?,?,?)',(sid,first(row,'geography','region','location'),first(row,'period','year','fiscal','date'),first(row,'service','program','custody','supervision'),first(row,'demographic','gender','age','identity'),metric,value,first(row,'unit'),dsid,rid,raw))
 elif table=='civil_forfeiture_statistics':
  c.execute('INSERT OR IGNORE INTO civil_forfeiture_statistics VALUES(?,?,?,?,?,?,?,?,?,?,?)',(sid,first(row,'geography','region','location','community'),first(row,'period','year','fiscal','date'),first(row,'proceeding','process','notice'),first(row,'asset','property','grant category','category'),metric,value,first(row,'unit'),dsid,rid,raw))
 elif table=='policing_statistics':
  c.execute('INSERT OR IGNORE INTO policing_statistics VALUES(?,?,?,?,?,?,?,?,?,?,?)',(sid,first(row,'geography','region','municipality','location'),first(row,'year','period','fiscal'),first(row,'police service','detachment','agency'),first(row,'subject','weapon','force type','category'),metric,value,first(row,'unit'),dsid,rid,raw))
 return True

def register_document(c,path,resource=None):
 b=path.read_bytes(); digest=sha_bytes(b); fmt=path.suffix.lstrip('.').upper() or 'FILE'
 did=str(uuid.uuid5(uuid.NAMESPACE_URL,digest))
 c.execute('''INSERT INTO source_documents(document_id,resource_id,dataset_id,source_type,title,source_url,local_path,retrieved_at,sha256,parse_status,raw_metadata)
 VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET retrieved_at=excluded.retrieved_at,local_path=excluded.local_path''',
 (did,resource['resource_id'] if resource else None,resource['dataset_id'] if resource else None,fmt,path.name,resource['url'] if resource else None,str(path.relative_to(ROOT)).replace('\\','/'),now(),digest,'indexed',json.dumps(dict(resource) if resource else {},default=str)))
 return did

def import_resource(c,r,courts):
 path=ROOT/(r['local_path'] or '')
 if not path.exists(): return 0,'missing',None
 fmt=(r['format'] or path.suffix.lstrip('.')).upper()
 run=c.execute("INSERT INTO import_runs(started_at,status,resource_id,local_path) VALUES(?,?,?,?)",(now(),'running',r['resource_id'],str(path))).lastrowid
 try:
  docid=register_document(c,path,r)
  if fmt in {'PDF','HTML','HTM'}:
   c.execute("UPDATE catalogue_resources SET import_state='indexed_document',imported_at=?,row_count=0,table_name='source_documents',import_error=NULL WHERE resource_id=?",(now(),r['resource_id']))
   c.execute("UPDATE import_runs SET finished_at=?,status='complete',table_name='source_documents' WHERE run_id=?",(now(),run)); c.commit(); return 0,'source_documents',docid
  rows=row_iter(path,fmt); count=0; table=None
  for i,row in enumerate(rows,1):
   if not isinstance(row,dict): row={'value':row}
   row=normalize_row(row)
   court=courthouse_match(row,courts); raw=json.dumps(row,ensure_ascii=False,default=str,sort_keys=True); rh=sha_bytes((r['resource_id']+raw).encode())
   c.execute('INSERT OR IGNORE INTO staging_rows(resource_id,dataset_id,source_document_id,row_number,courthouse_slug,raw_json,imported_at,row_hash) VALUES(?,?,?,?,?,?,?,?)',(r['resource_id'],r['dataset_id'],docid,i,court,raw,now(),rh))
   if table is None: table=classify_table((r['dataset_title'] or '')+' '+(r['name'] or ''),list(row))
   insert_stat(c,table,row,r['dataset_id'],r['resource_id'],docid,court)
   count+=1
  c.execute("UPDATE catalogue_resources SET import_state='imported',imported_at=?,row_count=?,table_name=?,import_error=NULL WHERE resource_id=?",(now(),count,table or 'staging_rows',r['resource_id']))
  c.execute("UPDATE import_runs SET finished_at=?,status='complete',row_count=?,table_name=? WHERE run_id=?",(now(),count,table or 'staging_rows',run)); c.commit(); return count,table,docid
 except Exception as e:
  c.execute("UPDATE catalogue_resources SET import_state='failed',import_error=? WHERE resource_id=?",(str(e),r['resource_id']))
  c.execute("UPDATE import_runs SET finished_at=?,status='failed',error_text=? WHERE run_id=?",(now(),str(e),run)); c.commit(); return 0,'failed',None

def apply_policy(c):
 p=load_policy(); auto=set(p['auto_enable_formats']); docs=set(p['document_formats']); ignored=set(p['ignored_formats'])
 for r in c.execute('SELECT resource_id,dataset_id,format,collection_state FROM catalogue_resources').fetchall():
  override=p.get('resource_overrides',{}).get(r['resource_id']) or p.get('dataset_overrides',{}).get(r['dataset_id'])
  state=override or ('ignored' if r['format'] in ignored else 'enabled' if r['format'] in auto else 'review' if r['format'] in docs else 'review')
  c.execute('UPDATE catalogue_resources SET collection_state=? WHERE resource_id=?',(state,r['resource_id']))
 c.commit()

def import_all(c):
 apply_policy(c)
 courts=json.loads((DATA/'courthouses.json').read_text(encoding='utf-8'))
 resources=c.execute('''SELECT r.*,d.title dataset_title FROM catalogue_resources r JOIN catalogue_datasets d ON d.dataset_id=r.dataset_id
 WHERE r.collection_state='enabled' AND r.local_path IS NOT NULL AND (r.imported_at IS NULL OR r.download_sha256 IS NOT NULL AND r.download_sha256 != COALESCE((SELECT sha256 FROM source_documents sd WHERE sd.resource_id=r.resource_id ORDER BY retrieved_at DESC LIMIT 1),''))''').fetchall()
 total=0
 for r in resources:
  n,table,_=import_resource(c,r,courts); total+=n; print(f"{r['name'] or r['resource_id']}: {n} rows -> {table}")
 return len(resources),total

def courthouse_summary(c, tables_now):
 court_counts={}
 def add_counts(rows):
  for row in rows:
   item=dict(row); slug=str(item.pop('courthouse_slug','') or '').strip()
   if not slug: continue
   current=court_counts.setdefault(slug,{'courthouse_slug':slug})
   for key,value in item.items(): current[key]=int(value or 0)

 add_counts(c.execute("""SELECT courthouse_slug,COUNT(*) imported_rows
  FROM staging_rows WHERE trim(COALESCE(courthouse_slug,''))<>'' GROUP BY courthouse_slug"""))
 if 'cases' in tables_now:
  add_counts(c.execute("""SELECT courthouse_slug,
   COUNT(*) case_records,
   SUM(CASE WHEN lower(COALESCE(verification_state,'')) IN ('verified','source-verified')
     AND lower(COALESCE(NULLIF(final_outcome,''),legal_status,'')) IN ('convicted','guilty','guilty plea','sentenced','acquitted','stayed','withdrawn','dismissed') THEN 1 ELSE 0 END) verified_outcomes,
   SUM(CASE WHEN lower(COALESCE(verification_state,'')) NOT IN ('verified','source-verified') THEN 1 ELSE 0 END) needs_review
   FROM cases WHERE trim(COALESCE(courthouse_slug,''))<>'' GROUP BY courthouse_slug"""))
 if 'daily_appearances' in tables_now:
  add_counts(c.execute("""SELECT courthouse_slug,COUNT(*) appearance_records
   FROM daily_appearances WHERE trim(COALESCE(courthouse_slug,''))<>'' GROUP BY courthouse_slug"""))
 if 'published_judgments' in tables_now:
  add_counts(c.execute("""SELECT courthouse_slug,
   COUNT(*) judgment_records,
   SUM(CASE WHEN lower(COALESCE(verification_state,'')) IN ('verified','source-verified')
     AND lower(COALESCE(outcome_type,'')) IN ('convicted','guilty','guilty plea','sentenced','acquitted','stayed','withdrawn','dismissed') THEN 1 ELSE 0 END) judgment_verified_outcomes,
   SUM(CASE WHEN lower(COALESCE(verification_state,'')) NOT IN ('verified','source-verified') THEN 1 ELSE 0 END) judgment_needs_review
   FROM published_judgments WHERE trim(COALESCE(courthouse_slug,''))<>'' GROUP BY courthouse_slug"""))
 if 'court_statistics' in tables_now:
  add_counts(c.execute("""SELECT courthouse_slug,COUNT(*) statistic_records
   FROM court_statistics WHERE trim(COALESCE(courthouse_slug,''))<>'' GROUP BY courthouse_slug"""))
 court=[]
 for item in court_counts.values():
  item['verified_outcomes']=int(item.get('verified_outcomes',0))+int(item.pop('judgment_verified_outcomes',0))
  item['needs_review']=int(item.get('needs_review',0))+int(item.pop('judgment_needs_review',0))
  item['local_records']=int(item.get('case_records',0))+int(item.get('appearance_records',0))+int(item.get('judgment_records',0))+int(item.get('statistic_records',0))
  item['linked_records']=max(item['local_records'],int(item.get('imported_rows',0)))
  court.append(item)
 return sorted(court,key=lambda item:item['courthouse_slug'])

def export(c):
 DATA.mkdir(exist_ok=True)
 rebuild_from_normalized_sources(c)
 tables_now={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 datasets=[]
 if 'catalogue_datasets' in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
  for d in c.execute('''SELECT d.dataset_id,d.title,d.organization,d.metadata_modified,d.catalogue_url,d.matched_terms,d.collection_state,d.priority,
   COUNT(r.resource_id) resources,SUM(CASE WHEN r.collection_state='enabled' THEN 1 ELSE 0 END) enabled,
   SUM(CASE WHEN r.import_state='imported' THEN 1 ELSE 0 END) imported,SUM(COALESCE(r.row_count,0)) rows,
   GROUP_CONCAT(DISTINCT r.format) formats
   FROM catalogue_datasets d LEFT JOIN catalogue_resources r ON r.dataset_id=d.dataset_id GROUP BY d.dataset_id ORDER BY d.priority DESC,d.title'''):
   datasets.append({**dict(d),'matched_terms':json.loads(d['matched_terms'] or '[]'),'formats':(d['formats'] or '').split(',') if d['formats'] else []})
 resources=[dict(r) for r in c.execute('''SELECT r.resource_id,r.dataset_id,d.title dataset_title,r.name,r.format,r.url,r.local_path,r.collection_state,r.import_state,r.import_error,r.imported_at,r.row_count,r.table_name FROM catalogue_resources r JOIN catalogue_datasets d ON d.dataset_id=r.dataset_id ORDER BY d.title,r.name''')] if datasets else []
 reviews=[dict(r) for r in c.execute("SELECT * FROM review_queue WHERE status='open' ORDER BY CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,created_at DESC LIMIT 500")]
 dismissed_reviews=[dict(r) for r in c.execute("SELECT * FROM dismissed_review_archive ORDER BY dismissed_at DESC")] if 'dismissed_review_archive' in tables_now else []
 # Surface collection-policy decisions and failed imports in the same review queue
 # displayed by the dashboard. These are derived reviews and are not inserted
 # into review_queue, preventing duplicate database rows on every export.
 review_keys={(r.get('entity_type'),r.get('entity_id'),r.get('reason')) for r in reviews}
 for r in c.execute('''SELECT r.resource_id,r.name resource_name,r.collection_state,r.import_state,r.import_error,r.url,d.title dataset_title
   FROM catalogue_resources r JOIN catalogue_datasets d ON d.dataset_id=r.dataset_id
   WHERE r.collection_state='review' OR r.import_state='failed'
   ORDER BY CASE WHEN r.import_state='failed' THEN 1 ELSE 2 END,d.title,r.name'''):
  if r['import_state']=='failed':
   reason='Import failed'
   severity='high'
   detail=r['import_error'] or 'The resource could not be imported.'
  else:
   reason='Collection policy decision required'
   severity='medium'
   detail='Choose whether this resource should be enabled or ignored.'
  key=('catalogue_resource',r['resource_id'],reason)
  if key in review_keys: continue
  reviews.append({'review_id':'derived-'+r['resource_id']+'-'+('failed' if r['import_state']=='failed' else 'policy'),
   'entity_type':'catalogue_resource','entity_id':r['resource_id'],'reason':reason,'severity':severity,
   'status':'open','created_at':'','dataset_title':r['dataset_title'],'resource_name':r['resource_name'],
   'detail':detail,'url':r['url']})
 runs=[dict(r) for r in c.execute('SELECT * FROM import_runs ORDER BY run_id DESC LIMIT 100')]
 counts={t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('staging_rows','source_documents','court_statistics','crime_statistics','prosecution_statistics','custody_statistics','youth_justice_statistics','civil_forfeiture_statistics','policing_statistics','cases','people','review_queue')}
 write_json_atomic(DATA/'data-manager.json', {'generatedAt':now(),'counts':counts,'datasets':datasets,'resources':resources,'runs':runs})
 write_json_atomic(DATA/'review-queue.json', {'generatedAt':now(),'reviews':reviews})
 write_json_atomic(DATA/'review-dismissed-archive.json', {'generatedAt':now(),'dismissedReviews':dismissed_reviews})
 write_json_atomic(DATA/'person-collection-metrics.json', {'generatedAt':now(),**collection_metrics(c)})
 explorer=[]
 for t in ('court_statistics','crime_statistics','prosecution_statistics','custody_statistics','youth_justice_statistics','civil_forfeiture_statistics','policing_statistics'):
  for r in c.execute(f'SELECT * FROM {t} ORDER BY rowid DESC LIMIT 500'): explorer.append({'type':t,**dict(r)})
 write_json_atomic(DATA/'data-explorer.json', {'generatedAt':now(),'records':explorer})
 court=courthouse_summary(c,tables_now)
 write_json_atomic(DATA/'courthouse-data.json', {'generatedAt':now(),'courthouses':court})
 # High-value chart datasets. Each dataset preserves legal-status boundaries.
 court_activity=[]
 if 'daily_appearances' in tables_now:
  cols={r[1] for r in c.execute('PRAGMA table_info(daily_appearances)')}
  current_clause='WHERE COALESCE(is_current,1)=1' if 'is_current' in cols else ''
  query=f"""SELECT substr(list_date,1,7) month,
    COALESCE(NULLIF(courthouse_name,''),NULLIF(courthouse_slug,''),'Unknown') courthouse,
    COUNT(*) appearances,COUNT(DISTINCT NULLIF(court_file_number,'')) distinct_files
    FROM daily_appearances {current_clause}
    GROUP BY substr(list_date,1,7),COALESCE(NULLIF(courthouse_name,''),NULLIF(courthouse_slug,''),'Unknown')
    ORDER BY month DESC,appearances DESC LIMIT 120"""
  for r in c.execute(query): court_activity.append(dict(r))
 if not court_activity and 'staging_rows' in tables_now:
  query="""SELECT substr(imported_at,1,7) month,
    COALESCE(NULLIF(courthouse_slug,''),'Unknown') courthouse,
    COUNT(*) appearances,COUNT(DISTINCT NULLIF(resource_id,'')) distinct_files
    FROM staging_rows WHERE COALESCE(courthouse_slug,'')!=''
    GROUP BY substr(imported_at,1,7),COALESCE(NULLIF(courthouse_slug,''),'Unknown')
    ORDER BY month DESC,appearances DESC LIMIT 120"""
  for r in c.execute(query): court_activity.append(dict(r))

 verified_outcomes=[]
 if 'cases' in tables_now:
  allowed=('convicted','acquitted','stayed','dismissed','withdrawn')
  query="""SELECT substr(COALESCE(outcome_date,closed_date),1,7) month,
    lower(COALESCE(NULLIF(final_outcome,''),legal_status)) outcome,COUNT(*) count
    FROM cases
    WHERE lower(COALESCE(verification_state,''))='verified'
      AND lower(COALESCE(NULLIF(final_outcome,''),legal_status)) IN (?,?,?,?,?)
      AND COALESCE(outcome_date,closed_date) IS NOT NULL
    GROUP BY substr(COALESCE(outcome_date,closed_date),1,7),lower(COALESCE(NULLIF(final_outcome,''),legal_status))
    ORDER BY month DESC,outcome"""
  for r in c.execute(query,allowed): verified_outcomes.append(dict(r))
 if not verified_outcomes and 'published_judgments' in tables_now:
  cols={r[1] for r in c.execute('PRAGMA table_info(published_judgments)')}
  if {'decision_date','outcome_type','verification_state'}.issubset(cols):
   query="""SELECT substr(decision_date,1,7) month,
     lower(outcome_type) outcome,COUNT(*) count
     FROM published_judgments
     WHERE lower(COALESCE(verification_state,''))='verified'
       AND lower(COALESCE(outcome_type,'')) IN (?,?,?,?,?)
       AND COALESCE(decision_date,'')!=''
     GROUP BY substr(decision_date,1,7),lower(outcome_type)
     ORDER BY month DESC,outcome"""
   for r in c.execute(query,allowed): verified_outcomes.append(dict(r))

 crime_severity=[]
 if 'statcan_crime_statistics' in tables_now:
  query="""SELECT ref_date year,geography region,
    COALESCE(NULLIF(metric,''),NULLIF(statistics,''),violation) metric,value,unit
    FROM statcan_crime_statistics
    WHERE value IS NOT NULL AND (
      lower(COALESCE(metric,'')) LIKE '%severity%' OR
      lower(COALESCE(statistics,'')) LIKE '%rate%' OR
      lower(COALESCE(metric,'')) LIKE '%rate%')
    ORDER BY ref_date DESC,geography,metric LIMIT 160"""
  for r in c.execute(query): crime_severity.append(dict(r))
 if not crime_severity and 'crime_statistics' in tables_now:
  query="""SELECT year,geography region,COALESCE(NULLIF(metric,''),offence_category) metric,value,unit
    FROM crime_statistics
    WHERE value IS NOT NULL AND (
      lower(COALESCE(metric,'')) LIKE '%severity%' OR
      lower(COALESCE(metric,'')) LIKE '%rate%')
    ORDER BY year DESC,geography,metric LIMIT 160"""
  for r in c.execute(query): crime_severity.append(dict(r))
 write_json_atomic(DATA/'charts-summary.json', {
  'generatedAt':now(),
  'courtActivity':court_activity,
  'verifiedOutcomes':verified_outcomes,
  'crimeSeverity':crime_severity,
  'counts':{'courtActivity':len(court_activity),'verifiedOutcomes':len(verified_outcomes),'crimeSeverity':len(crime_severity)},
  'sourceTables':sorted(tables_now),
  'notices':{
   'courtActivity':'Scheduled appearances and distinct court files only; court-list appearances are not charges or convictions.',
   'verifiedOutcomes':'Only cases marked verified with an explicit final outcome are counted.',
   'crimeSeverity':'Aggregate police-reported statistics; these figures do not establish individual guilt or case outcomes.'
  }
 })

 # Homepage case/person records. This is generated from the SQLite index rather
 # than browser localStorage, so courthouse/location searches work immediately.
 record_rows=[]
 if {'cases','people','case_people'}.issubset({r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}):
  query='''
   SELECT c.case_id,c.court_file_number,c.citation,c.court_level,c.courthouse_slug,
          c.case_title,c.opened_date,c.closed_date,c.legal_status,c.final_outcome,
          c.outcome_date,c.verification_state,c.source_url,c.retrieved_at,
          p.display_name,cp.role,
          GROUP_CONCAT(DISTINCT ch.offence_text) offences
   FROM cases c
   LEFT JOIN case_people cp ON cp.case_id=c.case_id
   LEFT JOIN people p ON p.person_id=cp.person_id
   LEFT JOIN charges ch ON ch.case_id=c.case_id
   GROUP BY c.case_id,p.person_id,cp.role
   ORDER BY COALESCE(c.outcome_date,c.closed_date,c.opened_date,c.retrieved_at) DESC
   LIMIT 10000
  '''
  for r in c.execute(query):
   court_name=(r['court_level'] or '').strip()
   location=(r['courthouse_slug'] or '').replace('-',' ').title()
   status=(r['final_outcome'] or r['legal_status'] or 'unknown').lower().replace(' ','_')
   record_rows.append({
    'id':r['case_id'],'name':r['display_name'] or r['case_title'] or 'Unnamed case',
    'offence':r['offences'] or '', 'status':status,
    'fileNumber':r['court_file_number'] or '', 'citation':r['citation'] or '',
    'court':court_name, 'location':location,
    'date':r['outcome_date'] or r['closed_date'] or r['opened_date'] or '',
    'verification':r['verification_state'] or 'review',
    'sourceUrl':r['source_url'] or '', 'retrievedAt':r['retrieved_at'] or '',
    'role':r['role'] or ''
   })
 write_json_atomic(DATA/'case-person-records.json', {'generatedAt':now(),'records':record_rows})

 # Unified search index and SQLite FTS5 index. The browser loads one compact,
 # pre-normalized file while SQLite retains a fast full-text index for local tools.
 search_rows=[]
 tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
 if {'cases','people','case_people'}.issubset(tables):
  query='''
   SELECT c.case_id,c.court_file_number,c.citation,c.court_level,c.courthouse_slug,
          c.case_title,c.opened_date,c.closed_date,c.legal_status,c.final_outcome,
          c.outcome_date,c.verification_state,c.source_url,c.retrieved_at,c.notes,
          (SELECT GROUP_CONCAT(display_name,' || ') FROM (SELECT DISTINCT p.display_name display_name FROM case_people cp JOIN people p ON p.person_id=cp.person_id WHERE cp.case_id=c.case_id)) names,
          (SELECT GROUP_CONCAT(offence_text,' || ') FROM (SELECT DISTINCT ch.offence_text offence_text FROM charges ch WHERE ch.case_id=c.case_id)) offences,
          (SELECT GROUP_CONCAT(sentence_text,' || ') FROM (SELECT DISTINCT o.sentence_text sentence_text FROM outcomes o WHERE o.case_id=c.case_id AND o.sentence_text IS NOT NULL AND o.sentence_text!='')) sentences
   FROM cases c
  '''
  for r in c.execute(query):
   names=[x.strip() for x in str(r['names'] or '').split(' || ') if x.strip()]
   variants=[]
   for name in names: variants.extend(name_variants(name))
   location=(r['courthouse_slug'] or '').replace('-',' ').title()
   title=r['case_title'] or r['citation'] or r['court_file_number'] or (names[0] if names else 'Case record')
   outcome=r['final_outcome'] or r['legal_status'] or 'unknown'
   fields=[title,*variants,r['court_file_number'],normalize_file_number(r['court_file_number']),r['citation'],r['offences'],outcome,r['sentences'],r['court_level'],location,r['notes']]
   search_rows.append({
    'id':r['case_id'],'type':'case','title':title,'names':names,'name_variants':sorted(set(variants)),
    'court_file':r['court_file_number'] or '','court_file_normalized':normalize_file_number(r['court_file_number']),
    'citation':r['citation'] or '','offences':[x.strip() for x in str(r['offences'] or '').split(' || ') if x.strip()],
    'outcome':outcome,'sentence':r['sentences'] or '','court':r['court_level'] or '',
    'location':location,'date':r['outcome_date'] or r['closed_date'] or r['opened_date'] or '',
    'verification':r['verification_state'] or 'review','record_status':'current','source_url':r['source_url'] or '',
    'search_normalized':normalize_search(' '.join(str(x or '') for x in fields))
   })
 if 'published_judgments' in tables:
  cols=columns(c,'published_judgments')
  wanted=[x for x in ('judgment_id','citation','case_name','case_title','title','court','court_level','decision_date','source_url','verification_state','outcome','outcome_type','sentence_text','summary','decision_text','source_category','collection_year') if x in cols]
  if wanted:
   for r in c.execute(f"SELECT {','.join(wanted)} FROM published_judgments"):
    d=dict(r); rid=d.get('judgment_id') or d.get('citation') or str(uuid.uuid4())
    title=d.get('case_name') or d.get('case_title') or d.get('title') or d.get('citation') or 'Published judgment'
    court=d.get('court') or d.get('court_level') or ''
    outcome=d.get('outcome') or d.get('outcome_type') or ''
    decision_text=d.get('decision_text') or ''
    names=[]
    case_match=re.split(r'\s+v\.?\s+',title,flags=re.I)
    if len(case_match)==2:
     names=[x.strip() for x in case_match if x.strip() and x.strip().casefold() not in ('r','the king','the queen')]
    if 'person_mentions' in tables:
     enriched=[x[0] for x in c.execute("SELECT DISTINCT exact_name FROM person_mentions WHERE source_entity_id=? AND source_entity_type IN ('judgment_enriched','judgment_body') ORDER BY confidence DESC,exact_name",(str(rid),))]
     names=list(dict.fromkeys([*names,*enriched]))
    fields=[title,*names,d.get('citation'),court,outcome,d.get('sentence_text'),d.get('summary'),decision_text,d.get('source_category'),d.get('collection_year')]
    search_rows.append({'id':rid,'type':'judgment','title':title,'names':names,'name_variants':[v for n in names for v in name_variants(n)],
     'court_file':'','court_file_normalized':'','citation':d.get('citation') or '','offences':[],
     'outcome':outcome,'sentence':d.get('sentence_text') or '','court':court,
     'location':'','date':d.get('decision_date') or str(d.get('collection_year') or ''),'verification':d.get('verification_state') or 'review',
     'record_status':'current','source_url':d.get('source_url') or '','search_normalized':normalize_search(' '.join(str(x or '') for x in fields))})

 # Daily court-list records are scheduled appearances, not findings of guilt.
 # Keep current and superseded versions searchable with an explicit status.
 if 'daily_appearances' in tables:
  cols=columns(c,'daily_appearances')
  wanted=[x for x in ('appearance_id','participant_name','court_file_number','courthouse_name','courtroom','appearance_date','list_date','appearance_time','appearance_reason','is_current','superseded_at','document_version_id') if x in cols]
  if wanted:
   for r in c.execute(f"SELECT {','.join(wanted)} FROM daily_appearances"):
    d=dict(r); current=bool(d.get('is_current',1)); file=d.get('court_file_number') or ''
    person=d.get('participant_name') or ''; location=d.get('courthouse_name') or ''
    date=d.get('appearance_date') or d.get('list_date') or ''
    title=' · '.join(x for x in (person,file,location) if x) or 'Scheduled court appearance'
    fields=[title,person,file,location,d.get('courtroom'),date,d.get('appearance_time'),d.get('appearance_reason')]
    search_rows.append({'id':str(d.get('appearance_id')),'type':'case','subtype':'court-list appearance','title':title,
     'names':[person] if person else [],'name_variants':name_variants(person),'court_file':file,
     'court_file_normalized':normalize_file_number(file),'citation':'','offences':[],
     'outcome':'Scheduled appearance','sentence':'','court':'','location':location,'date':date,
     'verification':'review','record_status':'current' if current else 'superseded',
     'source_url':'today-court.html','document_version_id':d.get('document_version_id') or '',
     'legal_notice':'Scheduled appearance only; not a conviction or finding of guilt.',
     'search_normalized':normalize_search(' '.join(str(x or '') for x in fields))})
 # Deduplicate by stable source identifiers, preferring verified records.
 priority={'verified':3,'reviewed':2,'official':2,'review':1,'unverified':0}
 dedup={}
 for row in search_rows:
  key=(f"appearance:{row.get('id')}:{row.get('record_status','current')}" if row.get('subtype')=='court-list appearance' else None) or (row['court_file_normalized'] and f"file:{row['court_file_normalized']}:{normalize_search(row['location'])}") or (row['citation'] and f"citation:{normalize_search(row['citation'])}") or f"{row['type']}:{normalize_search(row['title'])}:{row['date']}"
  old=dedup.get(key)
  if old is None or priority.get(row['verification'],0)>priority.get(old['verification'],0): dedup[key]=row
 search_rows=list(dedup.values())
 generated_at=now()
 write_json_atomic(DATA/'search-index.json', {'generatedAt':generated_at,'records':search_rows})

 # Split indexes keep browser payloads smaller while preserving the unified index
 # for compatibility with older pages and local tools.
 case_rows=[r for r in search_rows if r.get('type')=='case']
 judgment_rows=[r for r in search_rows if r.get('type')=='judgment']
 people_rows=[]
 if 'person_mentions' in tables:
  for r in c.execute("""SELECT pm.*,p.display_name canonical_name,
   (SELECT GROUP_CONCAT(COALESCE(alias_name,alias_text),' || ') FROM person_aliases pa WHERE pa.person_id=pm.person_id) alias_names
   FROM person_mentions pm LEFT JOIN people p ON p.person_id=pm.person_id
   ORDER BY COALESCE(pm.event_date,pm.updated_at) DESC,pm.exact_name"""):
   d=dict(r); name=d.get('canonical_name') or d.get('exact_name')
   aliases=[x.strip() for x in str(d.get('alias_names') or '').split(' || ') if x.strip()]
   variants=sorted(set(name_variants(name)+[v for alias in aliases for v in name_variants(alias)]))
   people_rows.append({
    'id':f"mention:{d.get('mention_id')}",'type':'person','title':name,
    'names':list(dict.fromkeys([x for x in [name,d.get('exact_name'),*aliases] if x])),
    'name_variants':variants,'person_id':d.get('person_id') or '',
    'role':d.get('role') or 'unknown','legal_status':d.get('legal_status') or 'unknown',
    'court_file':d.get('court_file_number') or '',
    'court_file_normalized':normalize_file_number(d.get('court_file_number')),
    'citation':'','offences':[d.get('offence_text')] if d.get('offence_text') else [],
    'outcome':d.get('legal_status') or 'unknown','sentence':'','court':d.get('court') or '',
    'location':d.get('location') or '','date':d.get('event_date') or '',
    'verification':d.get('verification_state') or 'review','record_status':'current',
    'source_url':d.get('source_url') or '', 'source_document_id':d.get('source_document_id') or '',
    'source_entity_type':d.get('source_entity_type') or '', 'source_entity_id':d.get('source_entity_id') or '',
    'raw_context':d.get('raw_context') or '',
    'search_normalized':normalize_search(' '.join(str(x or '') for x in [name,d.get('exact_name'),*variants,d.get('role'),d.get('legal_status'),d.get('court_file_number'),d.get('offence_text'),d.get('court'),d.get('location'),d.get('raw_context')]))
   })
 else:
  seen_people=set()
  for case in case_rows:
   for name in case.get('names') or []:
    normalized=normalize_search(name)
    if not normalized: continue
    person_key=(normalized,case.get('id'))
    if person_key in seen_people: continue
    seen_people.add(person_key)
    variants=name_variants(name)
    people_rows.append({'id':f"person:{normalize_file_number(case.get('id'))}:{normalize_file_number(name)}",'type':'person','title':name,'names':[name],'name_variants':variants,'court_file':case.get('court_file',''),'court_file_normalized':case.get('court_file_normalized',''),'citation':case.get('citation',''),'offences':case.get('offences',[]),'outcome':case.get('outcome',''),'sentence':case.get('sentence',''),'court':case.get('court',''),'location':case.get('location',''),'date':case.get('date',''),'verification':case.get('verification','review'),'record_status':case.get('record_status','current'),'source_url':case.get('source_url',''),'case_id':case.get('id'),'search_normalized':normalize_search(' '.join([name,*variants,case.get('court_file',''),case.get('citation',''),' '.join(case.get('offences',[])),case.get('outcome',''),case.get('court',''),case.get('location','')]))})

 statistics_rows=[]
 statistics_tables=('court_statistics','custody_statistics','crime_statistics','youth_justice_statistics','civil_forfeiture_statistics','police_observations','statcan_crime')
 for table in statistics_tables:
  if table not in tables: continue
  cols=columns(c,table)
  wanted=[x for x in ('id','record_id','stat_id','metric','measure','category','geography','region','courthouse_slug','facility','year','period','fiscal_year','value','unit','dataset_id','resource_id','source_document_id','source_url','verification_state','notes') if x in cols]
  if not wanted: continue
  for i,r in enumerate(c.execute(f"SELECT {','.join(wanted)} FROM {table} LIMIT 10000")):
   d=dict(r); metric=d.get('metric') or d.get('measure') or d.get('category') or table.replace('_',' ').title()
   geography=d.get('geography') or d.get('region') or d.get('courthouse_slug') or d.get('facility') or ''
   period=d.get('year') or d.get('period') or d.get('fiscal_year') or ''
   value=d.get('value')
   title=' · '.join(str(x) for x in (metric,geography,period) if x not in (None,''))
   statistics_rows.append({
    'id':str(d.get('id') or d.get('record_id') or f'{table}:{i}'),'type':'statistics','title':title or table.replace('_',' ').title(),
    'names':[],'name_variants':[],'court_file':'','court_file_normalized':'','citation':'','offences':[],
    'outcome':'','sentence':'','court':'','location':str(geography),'date':str(period),
    'verification':d.get('verification_state') or 'official','record_status':'current','source_url':d.get('source_url') or '',
    'metric':metric,'value':value,'unit':d.get('unit') or '','domain':table,'dataset_id':d.get('dataset_id') or '','resource_id':d.get('resource_id') or '','source_document_id':d.get('source_document_id') or '','source_table':table,
    'search_normalized':normalize_search(' '.join(str(x or '') for x in (metric,geography,period,value,d.get('unit'),d.get('notes'),table)))
   })

 # Attach consistent provenance fields before writing browser/API indexes.
 for row in search_rows:
  row.setdefault('source_table', 'daily_appearances' if row.get('subtype')=='court-list appearance' else ({'case':'cases','judgment':'published_judgments'}.get(row.get('type'),'search_records')))
  row.setdefault('source_document_id','')
  row.setdefault('document_version_id',row.get('document_version_id',''))
  row.setdefault('collected_at','')
 for row in people_rows:
  row.setdefault('source_table','case_people')
  row.setdefault('source_document_id','')
  row.setdefault('document_version_id','')
  row.setdefault('collected_at','')
 for row in statistics_rows:
  row.setdefault('source_table',row.get('domain','statistics'))
  row.setdefault('source_document_id',row.get('source_document_id',''))
  row.setdefault('document_version_id','')
  row.setdefault('collected_at','')

 # Build a persistent courthouse alias registry. Canonical names prefer official
 # courthouse labels; shortened city/registry/court variants remain aliases.
 def court_norm(value): return normalize_search(value)
 def court_base(value):
  text=court_norm(value)
  for suffix in (' provincial court',' law courts',' courthouse',' court house',' registry',' supreme court'):
   if text.endswith(suffix): text=text[:-len(suffix)].strip()
  return text
 court_names=set()
 for row in case_rows+judgment_rows+statistics_rows:
  for value in (row.get('court'),row.get('location')):
   if str(value or '').strip(): court_names.add(str(value).strip())
 official=[]
 court_file=DATA/'courthouses.json'
 if court_file.exists():
  try:
   raw=json.loads(court_file.read_text(encoding='utf-8')); official=raw if isinstance(raw,list) else raw.get('courthouses',raw.get('records',[]))
  except Exception: official=[]
 for row in official:
  for value in (row.get('name'),row.get('courthouse_name'),row.get('city'),row.get('location')):
   if str(value or '').strip(): court_names.add(str(value).strip())
 by_base={}
 for name in sorted(court_names):
  base=court_base(name) or court_norm(name)
  score=(4 if any(x in court_norm(name) for x in ('law courts','provincial court','supreme court','courthouse')) else 1, len(name))
  if base not in by_base or score>by_base[base][0]: by_base[base]=(score,name)
 aliases=[]
 for name in sorted(court_names):
  base=court_base(name) or court_norm(name); canonical=by_base.get(base,((0,0),name))[1]
  aliases.append({'alias':name,'alias_normalized':court_norm(name),'canonical':canonical,'canonical_normalized':court_norm(canonical),'source':'official' if any(court_norm(name)==court_norm(str(r.get('name') or r.get('courthouse_name') or '')) for r in official) else 'indexed'})
  if base and base!=court_norm(name): aliases.append({'alias':base.title(),'alias_normalized':base,'canonical':canonical,'canonical_normalized':court_norm(canonical),'source':'derived'})
 c.execute('DELETE FROM courthouse_aliases')
 for a in {a['alias_normalized']:a for a in aliases}.values():
  c.execute('INSERT OR REPLACE INTO courthouse_aliases(alias_normalized,alias_name,canonical_name,canonical_normalized,source,updated_at) VALUES(?,?,?,?,?,?)',(a['alias_normalized'],a['alias'],a['canonical'],a['canonical_normalized'],a['source'],generated_at))
 write_json_atomic(DATA/'courthouse-aliases.json',{'generatedAt':generated_at,'aliases':list({a['alias_normalized']:a for a in aliases}.values())})

 split_indexes={
  'search-cases.json':case_rows,
  'search-people.json':people_rows,
  'search-judgments.json':judgment_rows,
  'search-statistics.json':statistics_rows,
 }
 for filename,rows in split_indexes.items():
  write_json_atomic(DATA/filename, {'generatedAt':generated_at,'records':rows})
 try:
  import hashlib
  all_search_rows=case_rows+people_rows+judgment_rows+statistics_rows
  old={r['record_id']:r['content_hash'] for r in c.execute('SELECT record_id,content_hash FROM search_records')}
  incoming=set(); changed=0
  for r in all_search_rows:
   rid=f"{r.get('type','record')}:{r.get('id','')}"; incoming.add(rid)
   payload=json.dumps(r,ensure_ascii=False,separators=(',',':'),sort_keys=True)
   digest=hashlib.sha256(payload.encode('utf-8')).hexdigest()
   if old.get(rid)==digest: continue
   c.execute('DELETE FROM search_fts WHERE record_id=?',(rid,))
   c.execute('''INSERT INTO search_fts(record_id,entity_type,title,names,court_file_number,offences,outcome,sentence,courthouse,city,source_text)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(rid,r.get('type',''),r.get('title',''),' | '.join(r.get('name_variants') or r.get('names') or []),r.get('court_file',''),
                ' | '.join(r.get('offences') or []),r.get('outcome',''),r.get('sentence',''),r.get('court',''),r.get('location',''),r.get('search_normalized','')))
   c.execute('''INSERT INTO search_records(record_id,entity_type,title,names,court_file_number,offences,outcome,sentence,court,location,record_date,verification,record_status,content_hash,payload_json,indexed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(record_id) DO UPDATE SET entity_type=excluded.entity_type,title=excluded.title,names=excluded.names,court_file_number=excluded.court_file_number,offences=excluded.offences,outcome=excluded.outcome,sentence=excluded.sentence,court=excluded.court,location=excluded.location,record_date=excluded.record_date,verification=excluded.verification,record_status=excluded.record_status,content_hash=excluded.content_hash,payload_json=excluded.payload_json,indexed_at=excluded.indexed_at''',
                (rid,r.get('type',''),r.get('title',''),' | '.join(r.get('names') or []),r.get('court_file',''),' | '.join(r.get('offences') or []),r.get('outcome',''),r.get('sentence',''),r.get('court',''),r.get('location',''),str(r.get('date','')),r.get('verification','unknown'),r.get('record_status','current'),digest,payload,generated_at))
   changed+=1
  stale=set(old)-incoming
  for rid in stale:
   c.execute('DELETE FROM search_fts WHERE record_id=?',(rid,)); c.execute('DELETE FROM search_records WHERE record_id=?',(rid,))
  for key,value in {'indexed_at':generated_at,'record_count':str(len(incoming)),'changed_count':str(changed),'removed_count':str(len(stale))}.items():
   c.execute('INSERT INTO search_index_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,value))
  c.commit()
  write_json_atomic(DATA/'search-status.json',{'generatedAt':generated_at,'recordsIndexed':len(incoming),'changed':changed,'removed':len(stale),'mode':'SQLite FTS5 with JSON fallback'})
 except sqlite3.OperationalError as exc:
  print(f'FTS5 index unavailable: {exc}',file=sys.stderr)

 def rows_for(table,limit=5000):
  return [dict(r) for r in c.execute(f'SELECT * FROM {table} ORDER BY rowid DESC LIMIT ?', (limit,))]
 def summary(records, geography_fields=('geography','region','courthouse_slug','facility'), period_fields=('year','period','fiscal_year')):
  total=len(records); values=[r.get('value') for r in records if isinstance(r.get('value'),(int,float))]
  geos={next((str(r.get(f)) for f in geography_fields if r.get(f)), '') for r in records}; geos.discard('')
  periods={next((str(r.get(f)) for f in period_fields if r.get(f)), '') for r in records}; periods.discard('')
  metrics={str(r.get('metric') or '') for r in records}; metrics.discard('')
  return {'records':total,'numericValues':len(values),'geographies':len(geos),'periods':len(periods),'metrics':len(metrics)}
 domains={
  'court-system':('court_statistics',{'title':'Court-system statistics','notice':'Administrative court statistics; not individual guilt findings.'}),
  'corrections-custody':('custody_statistics',{'title':'Corrections and custody','notice':'Aggregate custody and corrections data.'}),
  'crime-policing':('crime_statistics',{'title':'Crime and policing','notice':'Police-reported and administrative statistics; source definitions vary.'}),
  'youth-justice':('youth_justice_statistics',{'title':'Youth justice','notice':'Aggregate data only. Identifiable youth records are excluded.'}),
  'civil-forfeiture':('civil_forfeiture_statistics',{'title':'Civil forfeiture','notice':'Civil forfeiture is not a criminal conviction.'}),
 }
 # Add policing rows to the combined crime/policing dashboard.
 for name,(table,meta) in domains.items():
  recs=rows_for(table)
  if name=='crime-policing': recs += rows_for('policing_statistics')
  payload={'generatedAt':now(),**meta,'summary':summary(recs),'records':recs}
  write_json_atomic(DATA/f'{name}.json', payload)
 print('Static data snapshots exported.')

def queue_files(c,files):
 for f in files:
  p=Path(f).resolve()
  if not p.exists(): print(f'Missing: {p}',file=sys.stderr); continue
  register_document(c,p); print(f'Indexed {p.name}')
 c.commit()

def main(argv=None):
 ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
 sub.add_parser('setup'); sub.add_parser('import'); sub.add_parser('export'); sub.add_parser('all')
 q=sub.add_parser('queue'); q.add_argument('files',nargs='+')
 a=ap.parse_args(argv); c=connect(); setup(c)
 if a.cmd=='setup': print(f'Database ready: {DB}')
 elif a.cmd=='import': print('Imported:',import_all(c))
 elif a.cmd=='export': export(c)
 elif a.cmd=='all': import_all(c); export(c)
 elif a.cmd=='queue': queue_files(c,a.files); export(c)
 return 0
if __name__=='__main__': raise SystemExit(main())
