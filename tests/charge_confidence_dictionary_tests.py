from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_charge_confidence_entries_have_stable_anchors():
    text = (ROOT / 'js' / 'data-dictionary.js').read_text(encoding='utf-8')
    anchors = [
        'charge-confidence',
        'charge-confidence-confirmed',
        'charge-confidence-likely',
        'charge-confidence-possible',
        'charge-confidence-non-verified',
        'charge-confidence-not-available',
    ]
    for anchor in anchors:
        assert f"id:'{anchor}'" in text
    assert "id:'charge-unavailable'" not in text
    assert 'No charge record is currently linked to this appearance in the local index.' in text


def test_appearance_search_uses_one_charge_not_available_indicator():
    text = (ROOT / 'js' / 'appearance-search.js').read_text(encoding='utf-8')
    assert "'Confirmed':'charge-confidence-confirmed'" in text
    assert "'Charge Not Available':'charge-confidence-not-available'" in text
    assert "detailLine('Charge confidence',chargeConfidenceLink(tier),{html:true})" in text
    assert 'href="${esc(chargeConfidenceHref(tier))}"' in text
    assert "addFlag('Charge unavailable'" not in text
    assert 'data-dictionary.html#charge-unavailable' not in text
