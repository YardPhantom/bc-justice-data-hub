import json,sqlite3,tempfile,unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import search_api
class SearchQualityTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=search_api.DB;search_api.DB=Path(self.tmp.name)/'t.db';c=sqlite3.connect(search_api.DB);c.row_factory=sqlite3.Row
  c.executescript("""CREATE VIRTUAL TABLE search_fts USING fts5(record_id UNINDEXED,entity_type UNINDEXED,title,names,court_file_number,offences,outcome,sentence,courthouse,city,source_text);CREATE TABLE search_records(record_id TEXT PRIMARY KEY,entity_type TEXT,title TEXT,names TEXT,court_file_number TEXT,offences TEXT,outcome TEXT,sentence TEXT,court TEXT,location TEXT,record_date TEXT,verification TEXT,record_status TEXT,content_hash TEXT,payload_json TEXT,indexed_at TEXT);CREATE TABLE courthouse_aliases(alias_normalized TEXT PRIMARY KEY,alias_name TEXT,canonical_name TEXT,canonical_normalized TEXT,source TEXT,updated_at TEXT);""")
  rows=[{'id':'c1','type':'case','title':'R v Test','court_file':'12345','court_file_normalized':'12345','citation':'2026 BCPC 1','offences':['Assault'],'outcome':'','court':'Provincial Court','location':'Nanaimo Provincial Court','date':'2026-01-01','verification':'review','record_status':'current','source_table':'cases'}, {'id':'a1','type':'case','subtype':'court-list appearance','title':'Test · 12345','court_file':'12345','court_file_normalized':'12345','citation':'','offences':[],'outcome':'Scheduled appearance','court':'','location':'Nanaimo Provincial Court','date':'2026-01-02','verification':'review','record_status':'current','source_table':'daily_appearances'}, {'id':'s1','type':'statistics','title':'Admissions · BC · 2025','court_file':'','court_file_normalized':'','citation':'','offences':[],'outcome':'','court':'','location':'BC','date':'2025','verification':'official','record_status':'current','metric':'Admissions','dataset_id':'custody','unit':'persons','source_table':'custody_statistics'}]
  for r in rows:
   rid=r['type']+':'+r['id'];payload=json.dumps(r);c.execute('INSERT INTO search_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(rid,r['type'],r['title'],'',r['court_file'],'','', '',r['court'],r['location'],r['date'],r['verification'],r['record_status'],'x',payload,'2026-01-03'));c.execute('INSERT INTO search_fts VALUES(?,?,?,?,?,?,?,?,?,?,?)',(rid,r['type'],r['title'],'',r['court_file'],' '.join(r['offences']),r['outcome'],'',r['court'],r['location'],payload))
  c.execute("INSERT INTO courthouse_aliases VALUES('nanaimo','Nanaimo','Nanaimo Provincial Court','nanaimo provincial court','derived','2026')");c.execute("INSERT INTO courthouse_aliases VALUES('nanaimo provincial court','Nanaimo Provincial Court','Nanaimo Provincial Court','nanaimo provincial court','official','2026')");c.commit();c.close()
 def tearDown(self):search_api.DB=self.old;self.tmp.cleanup()
 def q(self,**kw):
  c=search_api.connect();res=search_api.search(c,{k:[str(v)] for k,v in kw.items()});c.close();return res
 def test_grouping_links_case_and_appearance(self):self.assertEqual(self.q(court='Nanaimo',recordStatus='current')['total'],1)
 def test_statistics_filters(self):self.assertEqual(self.q(type='statistics',metric='Admissions',dataset='custody',unit='persons')['total'],1)
 def test_superseded_exclusion(self):self.assertEqual(self.q(recordStatus='superseded')['total'],0)
 def test_provenance_retained(self):self.assertEqual(self.q(type='statistics')['records'][0]['source_table'],'custody_statistics')
if __name__=='__main__':unittest.main()
