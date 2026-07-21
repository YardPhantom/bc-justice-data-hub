import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

spec = importlib.util.spec_from_file_location('data_pipeline', TOOLS / 'data_pipeline.py')
data_pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(data_pipeline)


def test_courthouse_summary_counts_full_linked_datasets():
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript('''
      CREATE TABLE staging_rows(courthouse_slug TEXT);
      CREATE TABLE cases(courthouse_slug TEXT, verification_state TEXT, final_outcome TEXT, legal_status TEXT);
      CREATE TABLE daily_appearances(courthouse_slug TEXT);
      CREATE TABLE published_judgments(courthouse_slug TEXT, verification_state TEXT, outcome_type TEXT);
      CREATE TABLE court_statistics(courthouse_slug TEXT);
    ''')
    con.executemany('INSERT INTO staging_rows VALUES(?)', [('vancouver',), ('vancouver',)])
    con.executemany('INSERT INTO cases VALUES(?,?,?,?)', [
        ('vancouver', 'verified', 'convicted', 'convicted'),
        ('vancouver', 'source-verified', '', 'charged'),
        ('vancouver', 'review', '', 'charged'),
    ])
    con.executemany('INSERT INTO daily_appearances VALUES(?)', [('vancouver',)] * 4)
    con.executemany('INSERT INTO published_judgments VALUES(?,?,?)', [
        ('vancouver', 'verified', 'acquitted'),
        ('vancouver', 'review', 'unknown'),
    ])
    con.execute('INSERT INTO court_statistics VALUES(?)', ('vancouver',))

    summary = data_pipeline.courthouse_summary(con, {
        'staging_rows', 'cases', 'daily_appearances', 'published_judgments', 'court_statistics'
    })
    assert summary == [{
        'courthouse_slug': 'vancouver',
        'imported_rows': 2,
        'case_records': 3,
        'verified_outcomes': 2,
        'needs_review': 2,
        'appearance_records': 4,
        'judgment_records': 2,
        'statistic_records': 1,
        'local_records': 10,
        'linked_records': 10,
    }]


def test_detail_cards_use_full_matches_and_generated_summary():
    text = (ROOT / 'court' / 'detail.js').read_text(encoding='utf-8')
    assert 'const allAppearances' in text
    assert 'const allJudgments' in text
    assert 'summaryCount(summary' in text
    assert "summaryCount(summary, 'linked_records', 'local_records')" in text
    assert 'updateArticleCounts({' in text
    assert 'Article counts include the full matched datasets' in text
    assert "String(court.phone).replace" in text
