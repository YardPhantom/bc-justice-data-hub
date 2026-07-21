import csv
import importlib.util
import sqlite3
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('collect_justice_sources', ROOT / 'tools' / 'collect_justice_sources.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

CORE = '''
CREATE TABLE people(person_id TEXT PRIMARY KEY,display_name TEXT,normalized_name TEXT,review_required INTEGER,created_at TEXT,updated_at TEXT);
CREATE TABLE cases(case_id TEXT PRIMARY KEY,court_file_number TEXT,court_level TEXT,courthouse_slug TEXT,case_title TEXT,legal_status TEXT,final_outcome TEXT,outcome_date TEXT,verification_state TEXT,source_url TEXT,retrieved_at TEXT,notes TEXT, UNIQUE(court_file_number,courthouse_slug));
CREATE TABLE case_people(case_id TEXT,person_id TEXT,role TEXT,PRIMARY KEY(case_id,person_id,role));
CREATE TABLE charges(charge_id TEXT PRIMARY KEY,case_id TEXT,offence_text TEXT,statute TEXT,section TEXT,charge_date TEXT,charge_status TEXT,disposition TEXT,disposition_date TEXT,source_document_id TEXT);
CREATE TABLE case_events(event_id TEXT PRIMARY KEY,case_id TEXT,event_type TEXT,event_date TEXT,courtroom TEXT,courthouse_slug TEXT,description TEXT,source_document_id TEXT,verification_state TEXT);
CREATE TABLE review_queue(review_id TEXT PRIMARY KEY,entity_type TEXT,entity_id TEXT,reason TEXT,severity TEXT,source_document_id TEXT,status TEXT,created_at TEXT);
'''

def run_import(headers, values):
    c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
    c.executescript(CORE); mod.migrate(c)
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/'cso.csv'
        with p.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=headers); w.writeheader(); w.writerow(dict(zip(headers,values)))
        assert mod.import_cso(c,[p]) == (1,0)
    return c

def test_legacy_template_fields_are_imported():
    c=run_import(['person_name','file_number','court','location','status','offence','event_date'],['Jason Cole','12345','Vancouver','Vancouver','charged','Assault','2026-01-02'])
    assert c.execute('select display_name from people').fetchone()[0]=='Jason Cole'
    assert tuple(c.execute('select legal_status,courthouse_slug from cases').fetchone())==('charged','vancouver')
    assert c.execute('select offence_text from charges').fetchone()[0]=='Assault'

def test_canonical_template_fields_are_imported():
    c=run_import(['participant_name','court_file_number','courthouse','legal_status','offence_text'],['Jane Doe','A-9','Victoria','scheduled','Theft'])
    assert c.execute('select display_name from people').fetchone()[0]=='Jane Doe'
    assert c.execute('select legal_status from cases').fetchone()[0]=='scheduled_appearance'
    assert c.execute('select offence_text from charges').fetchone()[0]=='Theft'
