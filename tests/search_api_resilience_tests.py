import importlib.util, json, sqlite3, tempfile
from pathlib import Path

MOD=Path(__file__).resolve().parents[1]/'tools'/'search_api.py'
spec=importlib.util.spec_from_file_location('search_api',MOD)
api=importlib.util.module_from_spec(spec); spec.loader.exec_module(api)

def make_db(with_fts=True):
 c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
 c.execute('CREATE TABLE search_records(record_id TEXT,entity_type TEXT,title TEXT,names TEXT,court_file_number TEXT,offences TEXT,outcome TEXT,sentence TEXT,court TEXT,location TEXT,record_date TEXT,verification TEXT,record_status TEXT,payload_json TEXT,indexed_at TEXT)')
 payload={'id':'p1','type':'person','title':'John Smith','names':['John Smith'],'record_status':'current'}
 c.execute('INSERT INTO search_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('p1','person','John Smith','John Smith','','','','','','','2026-01-01','review','current',json.dumps(payload),'2026-01-01'))
 if with_fts:
  c.execute("CREATE VIRTUAL TABLE search_fts USING fts5(record_id UNINDEXED,title,names,court_file_number,offences,outcome,sentence,court,location,body)")
  # deliberately leave FTS empty to test direct fallback
 return c

def test_direct_fallback_when_fts_empty():
 c=make_db(True)
 result=api.search(c,{'q':['John Smith'],'type':['person'],'recordStatus':['current'],'group':['false']})
 assert result['total']==1
 assert result['records'][0]['title']=='John Smith'

def test_direct_fallback_when_fts_missing():
 c=make_db(False)
 result=api.search(c,{'q':['John'],'type':['person'],'recordStatus':['current'],'group':['false']})
 assert result['total']==1

def test_status_reports_actual_rows_without_meta_table():
 c=make_db(False)
 old=api.DB
 try:
  with tempfile.NamedTemporaryFile() as f:
   api.DB=Path(f.name)
   status=api.status_payload(c)
 finally:
  api.DB=old
 assert status['recordsIndexed']==1
 assert status['indexStatus'] in {'outdated','current'}

if __name__=='__main__':
 for fn in [test_direct_fallback_when_fts_empty,test_direct_fallback_when_fts_missing,test_status_reports_actual_rows_without_meta_table]:fn()
 print('search api resilience tests passed')

def make_appearance_db():
 c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.executescript(api.APPEARANCE_CACHE_SCHEMA)
 records=[
  {'appearance_id':'a1','participant_name':'SMITH, JOHN','court_file_number':'123-45','courthouse_name':'Vancouver Law Courts','list_date':'2026-07-20','appearance_time':'09:30','charge_confidence':'Confirmed'},
  {'appearance_id':'a2','participant_name':'SMITH, JOHN','court_file_number':'123-45','courthouse_name':'Vancouver Law Courts','list_date':'2026-07-19','appearance_time':'10:00','charge_confidence':'Likely'},
  {'appearance_id':'a3','participant_name':'SMITH, JANE','court_file_number':'999-00','courthouse_name':'Victoria Law Courts','list_date':'2026-07-18','appearance_time':'11:00','charge_confidence':'Possible'},
 ]
 for r in records:
  c.execute('INSERT INTO appearance_search_records VALUES(?,?,?,?,?,?,?,?,?,?)',(r['appearance_id'],r['participant_name'],api.appearance_norm(r['participant_name']),r['court_file_number'],api.appearance_file_norm(r['court_file_number']),r['courthouse_name'],r['list_date'],r['charge_confidence'],json.dumps(r),'2026-07-20'))
 return c

def test_appearance_api_partial_exact_filters_and_pagination():
 c=make_appearance_db()
 partial=api.search_appearances(c,{'name':['smith'],'match':['partial'],'limit':['1'],'offset':['0']})
 assert partial['total']==3 and len(partial['records'])==1
 assert partial['records'][0]['history_count']==2
 exact=api.search_appearances(c,{'name':['smith john'],'match':['exact'],'limit':['50'],'offset':['0']})
 assert exact['total']==2
 filtered=api.search_appearances(c,{'court':['Victoria Law Courts'],'confidence':['Possible'],'from':['2026-07-18'],'to':['2026-07-18']})
 assert filtered['total']==1 and filtered['records'][0]['participant_name']=='SMITH, JANE'

def test_appearance_api_history_uses_same_name_or_file():
 c=make_appearance_db()
 result=api.appearance_history(c,{'appearanceId':['a1']})
 assert result['total']==2
 assert [r['appearance_id'] for r in result['records']]==['a1','a2']

def test_appearance_cache_bootstraps_from_static_pages(tmp_path):
 data=tmp_path/'data';data.mkdir()
 first={'pageCount':2,'appearances':[{'appearance_id':'s1','participant_name':'DOE, ALEX','court_file_number':'11','courthouse_name':'Kelowna','list_date':'2026-07-20','charge_confidence':'Confirmed'}]}
 second={'appearances':[{'appearance_id':'s2','participant_name':'DOE, JAMIE','court_file_number':'12','courthouse_name':'Kelowna','list_date':'2026-07-19','charge_confidence':'Likely'}]}
 (data/'daily-court-lists.json').write_text(json.dumps(first),encoding='utf-8')
 (data/'daily-court-lists-page-2.json').write_text(json.dumps(second),encoding='utf-8')
 old_root,old_ready=api.ROOT,api.APPEARANCE_SCHEMA_READY
 try:
  api.ROOT=tmp_path;api.APPEARANCE_SCHEMA_READY=False
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
  result=api.search_appearances(c,{'name':['doe'],'limit':['50'],'offset':['0']})
 finally:
  api.ROOT=old_root;api.APPEARANCE_SCHEMA_READY=old_ready
 assert result['total']==2
 assert {r['participant_name'] for r in result['records']}=={'DOE, ALEX','DOE, JAMIE'}


def test_appearance_api_sort_modes():
 c=make_appearance_db()
 expected={
  'newest':['a1','a2','a3'],
  'oldest':['a3','a2','a1'],
  'name':['a3','a1','a2'],
  'courthouse':['a1','a2','a3'],
  'confidence':['a1','a2','a3'],
  'history':['a1','a2','a3'],
 }
 for sort,ids in expected.items():
  result=api.search_appearances(c,{'sort':[sort],'limit':['50'],'offset':['0']})
  assert result['sort']==sort
  assert [r['appearance_id'] for r in result['records']]==ids
 result=api.search_appearances(c,{'sort':['unsupported'],'limit':['50'],'offset':['0']})
 assert result['sort']=='newest'
 assert [r['appearance_id'] for r in result['records']]==expected['newest']
