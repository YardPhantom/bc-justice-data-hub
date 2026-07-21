#!/usr/bin/env python3
from __future__ import annotations
import importlib.util, sqlite3, tempfile, sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

m = load('collect_justice_sources', ROOT / 'tools' / 'collect_justice_sources.py')

def check(ok, msg):
    if not ok:
        raise AssertionError(msg)

def main():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        m.ROOT = base
        m.DB = base / 'database' / 'bc_justice.db'
        m.DATA = base / 'data'
        m.IMPORTS = base / 'imports'
        m.ARCHIVE = m.IMPORTS / 'justice-sources'
        m.DATA.mkdir(parents=True, exist_ok=True)
        m.IMPORTS.mkdir(parents=True, exist_ok=True)
        m.DB.parent.mkdir(parents=True, exist_ok=True)
        texts = {
            b'v1': 'Victoria Law Courts\n09:00\nAlex Example A1234',
            b'v2': 'Victoria Law Courts\n09:00\nAlex Example A1234\nJamie Example B5678',
        }
        m.parse_pdf = lambda raw: (texts[raw], 1, 'parsed')
        with closing(m.db()) as c:
            c.execute("CREATE TABLE IF NOT EXISTS review_queue(review_id TEXT PRIMARY KEY,entity_type TEXT,entity_id TEXT,reason TEXT,severity TEXT,source_document_id TEXT,status TEXT,created_at TEXT,resolved_at TEXT,resolution_notes TEXT)")
            c.commit()
            url = 'https://example.com/daily-list'
            first = m.store_daily_document(c, 'Daily criminal list', url, b'v1', 'application/pdf')
            second = m.store_daily_document(c, 'Daily criminal list', url, b'v2', 'application/pdf')
            c.commit()
            all_versions = c.execute('SELECT COUNT(*) FROM daily_court_document_versions WHERE document_key=?', (first['document_key'],)).fetchone()[0]
            current_rows = c.execute('SELECT COUNT(*) FROM daily_appearances WHERE document_key=? AND is_current=1', (first['document_key'],)).fetchone()[0]
            historical_rows = c.execute('SELECT COUNT(*) FROM daily_appearances WHERE document_key=?', (first['document_key'],)).fetchone()[0]
            old_row = c.execute('SELECT superseded_at FROM daily_appearances WHERE document_key=? AND is_current=0 LIMIT 1', (first['document_key'],)).fetchone()
            linked = c.execute('SELECT COUNT(*) FROM daily_appearances WHERE superseded_by_appearance_id IS NOT NULL', ()).fetchone()[0]
            check(first['new_version'] and second['new_version'], 'each changed file should create a stored version')
            check(all_versions == 2, 'document versions preserved')
            check(current_rows == 2, 'current version rows available')
            check(historical_rows == 3, 'older appearance rows retained instead of deleted')
            check(old_row and old_row['superseded_at'], 'superseded appearance tracked')
            check(linked >= 1, 'superseded appearance should point to replacement when matched')
    print('Daily court retention tests passed.')

if __name__ == '__main__':
    main()
