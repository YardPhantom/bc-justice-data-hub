import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def load(name, path):
    spec=importlib.util.spec_from_file_location(name, path)
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    spec.loader.exec_module(mod)
    return mod

pm=load('person_mentions_schema_test', ROOT/'tools'/'person_mentions.py')
pi=load('person_identity_schema_test', ROOT/'tools'/'person_identity.py')

class SchemaCompatibilityTests(unittest.TestCase):
    def test_daily_appearances_without_appearance_date(self):
        c=sqlite3.connect(':memory:')
        c.row_factory=sqlite3.Row
        pm.ensure_schema(c)
        c.executescript('''
        CREATE TABLE people(person_id TEXT PRIMARY KEY,display_name TEXT,normalized_name TEXT,identity_confidence REAL,review_required INTEGER,created_at TEXT,updated_at TEXT);
        CREATE TABLE daily_appearances(participant_name TEXT,court_file_number TEXT,courthouse_name TEXT,list_date TEXT);
        INSERT INTO daily_appearances VALUES('Jane Example','ABC-123','Nanaimo','2026-07-20');
        ''')
        # Should not reference a missing appearance_date column.
        count=pm.rebuild_from_normalized_sources(c)
        self.assertGreaterEqual(count,1)

    def test_alias_insert_with_expanded_schema(self):
        c=sqlite3.connect(':memory:')
        c.row_factory=sqlite3.Row
        c.executescript('''
        CREATE TABLE people(person_id TEXT PRIMARY KEY,display_name TEXT,normalized_name TEXT);
        INSERT INTO people VALUES('p1','Jane Example','jane example');
        CREATE TABLE person_aliases(
          alias_id TEXT PRIMARY KEY,person_id TEXT NOT NULL,alias_text TEXT NOT NULL,
          normalized_alias TEXT NOT NULL,alias_type TEXT,source_document_id TEXT,
          verified INTEGER,created_at TEXT,alias_name TEXT,source_entity_type TEXT,
          source_entity_id TEXT,verification_state TEXT,confidence REAL,updated_at TEXT,
          UNIQUE(person_id,normalized_alias));
        ''')
        self.assertGreaterEqual(pi.aliases(c),1)
        row=c.execute('SELECT alias_text,alias_name FROM person_aliases').fetchone()
        self.assertEqual(row['alias_name'],row['alias_text'])

if __name__=='__main__': unittest.main()
