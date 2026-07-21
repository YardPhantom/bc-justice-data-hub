from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_relationships_load_broad_indexes_and_show_details():
    text=(ROOT/'js'/'relationships.js').read_text(encoding='utf-8')
    for name in ('search-cases.json','search-people.json','person-mentions.json','daily-court-lists.json','published-judgments.json'):
        assert name in text
    assert 'matterNames' in text
    assert 'matterOffences' in text
    assert 'legal-note' in text
    assert 'Open records' in text

def test_relationship_page_has_live_summary():
    text=(ROOT/'relationships.html').read_text(encoding='utf-8')
    assert 'id="relSummary"' in text
    assert 'aria-live="polite"' in text

def test_private_notes_fallback_mentions_button():
    text=(ROOT/'js'/'private-notes.js').read_text(encoding='utf-8')
    assert r'Run tools\\notes.cmd export OR press the Export actions button' in text
