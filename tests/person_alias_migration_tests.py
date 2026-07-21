import sqlite3, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from person_mentions import ensure_alias_schema, record_alias


def test_legacy_alias_table_is_upgraded_in_place():
    c=sqlite3.connect(':memory:')
    c.row_factory=sqlite3.Row
    c.executescript('''
    CREATE TABLE person_aliases(
      alias_id TEXT PRIMARY KEY,person_id TEXT NOT NULL,alias_text TEXT NOT NULL,
      normalized_alias TEXT NOT NULL,alias_type TEXT DEFAULT 'published',
      source_document_id TEXT,verified INTEGER DEFAULT 0,created_at TEXT,
      UNIQUE(person_id,normalized_alias)
    );
    INSERT INTO person_aliases(alias_id,person_id,alias_text,normalized_alias,verified)
    VALUES('a1','p1','Jason Smith','jason smith',1);
    ''')
    ensure_alias_schema(c)
    cols={r[1] for r in c.execute('PRAGMA table_info(person_aliases)')}
    assert {'alias_name','source_entity_type','source_entity_id','verification_state','confidence','updated_at'} <= cols
    row=c.execute('SELECT alias_name,alias_text,verification_state FROM person_aliases').fetchone()
    assert row['alias_name']=='Jason Smith'
    assert row['alias_text']=='Jason Smith'
    assert row['verification_state']=='verified'
    record_alias(c,'p1','Jason Smith','case','c1','source_variant','review',0.7)
    assert c.execute('SELECT COUNT(*) FROM person_aliases').fetchone()[0]==1
