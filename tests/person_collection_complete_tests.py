import sqlite3, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from person_mentions import ensure_schema, ensure_alias_schema, extract_person_candidates, record_mention, rebuild_aliases_and_reviews, collection_metrics

def db():
 c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
 c.executescript('''
 CREATE TABLE people(person_id TEXT PRIMARY KEY,display_name TEXT,normalized_name TEXT,identity_confidence REAL,review_required INTEGER,created_at TEXT,updated_at TEXT);
 CREATE TABLE review_queue(review_id TEXT PRIMARY KEY,entity_type TEXT,entity_id TEXT,reason TEXT,severity TEXT,status TEXT,created_at TEXT,resolved_at TEXT,resolution_notes TEXT,source_document_id TEXT);
 '''); ensure_schema(c); ensure_alias_schema(c); return c

def test_phrase_extraction_preserves_status():
 rows=extract_person_candidates('Jason Cole was charged with theft. Jane Smith was acquitted.')
 assert any(x['name']=='Jason Cole' and x['legal_status']=='charged' for x in rows)
 assert any(x['name']=='Jane Smith' and x['legal_status']=='acquitted' for x in rows)

def test_alias_review_metrics():
 c=db(); record_mention(c,name='Cole, Jason',source_entity_type='police_report',source_entity_id='p1',role='unknown',legal_status='alleged',confidence=.5,raw_context='Jason Cole was arrested')
 rebuild_aliases_and_reviews(c)
 assert c.execute('select count(*) from person_aliases').fetchone()[0]==1
 assert c.execute("select count(*) from review_queue where entity_type='person_mention'").fetchone()[0]>=1
 m=collection_metrics(c); assert m['totalMentions']==1 and m['aliases']==1 and m['distinctNames']==1
