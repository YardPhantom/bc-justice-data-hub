import sqlite3, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import person_mentions as pm

def db():
 c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
 c.executescript('''CREATE TABLE people(person_id TEXT PRIMARY KEY,display_name TEXT NOT NULL,normalized_name TEXT,date_of_birth TEXT,identity_confidence REAL DEFAULT 0,review_required INTEGER DEFAULT 1,created_at TEXT,updated_at TEXT);
 CREATE TABLE cases(case_id TEXT PRIMARY KEY,court_file_number TEXT,case_title TEXT,legal_status TEXT,final_outcome TEXT,outcome_date TEXT,opened_date TEXT,verification_state TEXT,source_document_id TEXT,source_url TEXT,court_level TEXT,courthouse_slug TEXT);
 CREATE TABLE case_people(case_id TEXT,person_id TEXT,role TEXT); CREATE TABLE charges(case_id TEXT,offence_text TEXT);''')
 pm.ensure_schema(c); return c

def test_mention_keeps_scheduled_appearance_distinct_from_conviction():
 c=db(); pm.record_mention(c,name='Jason Smith',source_entity_type='court_list',source_entity_id='a1',role='accused',legal_status='scheduled appearance')
 row=c.execute('select * from person_mentions').fetchone()
 assert row['legal_status']=='scheduled_appearance'
 assert row['role']=='accused'

def test_same_name_sources_are_preserved_as_separate_mentions():
 c=db()
 pm.record_mention(c,name='Jason Smith',source_entity_type='court_list',source_entity_id='a1')
 pm.record_mention(c,name='Jason Smith',source_entity_type='case',source_entity_id='c1',legal_status='charged')
 assert c.execute('select count(*) from person_mentions').fetchone()[0]==2

def test_judgment_title_extracts_named_party_not_crown():
 assert pm.names_from_judgment_title('R. v. Jason Smith')==['Jason Smith']
