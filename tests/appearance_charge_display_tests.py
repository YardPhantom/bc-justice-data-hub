from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_shared_renderer_shows_linked_charge_and_safe_fallback():
    text = (ROOT / 'js' / 'appearance-search.js').read_text(encoding='utf-8')
    assert 'Linked alleged charge' in text
    assert 'Charge Not Available' in text
    assert 'No charge information  linked to this appearance.' in text
    assert 'Scheduled appearance — allegation not proven</small>' not in text

def test_daily_export_enriches_only_from_linked_case_charge_data():
    text = (ROOT / 'tools' / 'collect_justice_sources.py').read_text(encoding='utf-8')
    assert "appearance['linked_charges']" in text
    assert "appearance['alleged_charges']" in text
    assert "re.sub(r'[^a-z0-9]'" in text
    assert 'charge_confidence' in text
