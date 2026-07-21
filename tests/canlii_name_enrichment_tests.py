import sqlite3, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from person_mentions import rebuild_from_normalized_sources

class CanliiNameEnrichmentTests(unittest.TestCase):
 def make_db(self):
  c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
  c.executescript('''
  CREATE TABLE people(person_id TEXT PRIMARY KEY,display_name TEXT,normalized_name TEXT,identity_confidence REAL,review_required INTEGER,created_at TEXT,updated_at TEXT);
  CREATE TABLE cases(case_id TEXT PRIMARY KEY,court_file_number TEXT,case_title TEXT,legal_status TEXT,final_outcome TEXT,outcome_date TEXT,opened_date TEXT,verification_state TEXT,source_document_id TEXT,source_url TEXT,court_level TEXT,courthouse_slug TEXT,citation TEXT);
  CREATE TABLE case_people(case_id TEXT,person_id TEXT,role TEXT);
  CREATE TABLE charges(charge_id TEXT,case_id TEXT,offence_text TEXT);
  CREATE TABLE published_judgments(judgment_id TEXT PRIMARY KEY,case_title TEXT,citation TEXT,court_file_number TEXT,court_level TEXT,decision_date TEXT,source_url TEXT,verification_state TEXT,outcome_type TEXT,summary TEXT,decision_text TEXT,raw_metadata TEXT,publication_flags TEXT);
  CREATE TABLE review_queue(review_id TEXT PRIMARY KEY,entity_type TEXT,entity_id TEXT,reason TEXT,severity TEXT,status TEXT,created_at TEXT);
  CREATE TABLE person_aliases(alias_id TEXT PRIMARY KEY,person_id TEXT,alias_text TEXT,normalized_alias TEXT,alias_type TEXT,source_document_id TEXT,verified INTEGER,created_at TEXT,UNIQUE(person_id,normalized_alias));
  ''')
  return c
 def test_exact_citation_enriches_full_name(self):
  c=self.make_db()
  c.execute("INSERT INTO people VALUES('p1','Jordan Michael Smith','jordan michael smith',.9,0,'','')")
  c.execute("INSERT INTO cases VALUES('c1','12345-1','R. v. Smith','convicted','convicted','2025-01-01','2024-01-01','verified','','x','BCPC','nanaimo','2025 BCPC 10')")
  c.execute("INSERT INTO case_people VALUES('c1','p1','accused')")
  c.execute("INSERT INTO published_judgments VALUES('j1','R. v. J.S.','2025 BCPC 10','','BCPC','2025-01-01','https://canlii.org/x','verified','convicted','','','','')")
  rebuild_from_normalized_sources(c)
  row=c.execute("SELECT * FROM person_mentions WHERE source_entity_type='judgment_enriched'").fetchone()
  self.assertEqual(row['exact_name'],'Jordan Michael Smith')
  self.assertEqual(row['verification_state'],'verified')
 def test_anonymized_judgment_not_enriched(self):
  c=self.make_db()
  c.execute("INSERT INTO people VALUES('p1','Jordan Michael Smith','jordan michael smith',.9,0,'','')")
  c.execute("INSERT INTO cases VALUES('c1','12345-1','R. v. Smith','charged','','','2024-01-01','verified','','x','BCPC','nanaimo','2025 BCPC 11')")
  c.execute("INSERT INTO case_people VALUES('c1','p1','accused')")
  c.execute("INSERT INTO published_judgments VALUES('j1','R. v. J.S.','2025 BCPC 11','','BCPC','2025-01-01','https://canlii.org/x','review','','','','','publication ban; anonymized')")
  rebuild_from_normalized_sources(c)
  self.assertIsNone(c.execute("SELECT 1 FROM person_mentions WHERE source_entity_type='judgment_enriched'").fetchone())

if __name__=='__main__': unittest.main()
