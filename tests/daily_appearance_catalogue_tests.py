import importlib.util
import sqlite3
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
MODULE_PATH = ROOT / 'tools' / 'collect_justice_sources.py'
spec = importlib.util.spec_from_file_location('collect_justice_sources', MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_appearance_key_includes_date():
    text = '1 12345-1 SMITH, TONY  WAR'
    a = mod.extract_daily_rows(text, 'Provincial Court', 'https://example.test/a.pdf', 'doc', 'key', 'v1', '2026-07-20')
    b = mod.extract_daily_rows(text, 'Provincial Court', 'https://example.test/a.pdf', 'doc', 'key', 'v2', '2026-07-21')
    assert a and b
    assert a[0]['appearance_key'] != b[0]['appearance_key']


def test_catalogue_export_keeps_old_dates(tmp_path):
    old_db, old_data = mod.DB, mod.DATA
    try:
        mod.DB = tmp_path / 'test.db'
        mod.DATA = tmp_path / 'data'
        c = mod.db()
        c.execute('CREATE TABLE cases(case_id TEXT, source_url TEXT, notes TEXT, retrieved_at TEXT)')
        cols = [r[1] for r in c.execute('PRAGMA table_info(daily_appearances)')]
        values = {k: None for k in cols}
        values.update({
            'appearance_id':'a1','document_id':'d1','list_date':'2026-07-20','participant_name':'SMITH, TONY',
            'court_file_number':'12345-1','courthouse_name':'Nanaimo Law Courts','appearance_time':'09:30',
            'appearance_key':'k1','is_current':0,'first_seen_at':'2026-07-20T10:00:00+00:00','last_seen_at':'2026-07-20T10:00:00+00:00'
        })
        c.execute(f"INSERT INTO daily_appearances({','.join(cols)}) VALUES({','.join('?' for _ in cols)})", [values[x] for x in cols])
        values.update({'appearance_id':'a2','list_date':'2026-07-21','appearance_key':'k2','is_current':1,'first_seen_at':'2026-07-21T10:00:00+00:00','last_seen_at':'2026-07-21T10:00:00+00:00'})
        c.execute(f"INSERT INTO daily_appearances({','.join(cols)}) VALUES({','.join('?' for _ in cols)})", [values[x] for x in cols])
        c.commit()
        mod.export(c)
        import json
        payload=json.loads((mod.DATA/'daily-court-lists.json').read_text())
        assert payload['totalRecords']==2
        assert {r['list_date'] for r in payload['appearances']}=={'2026-07-20','2026-07-21'}
    finally:
        mod.DB, mod.DATA = old_db, old_data
