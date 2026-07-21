from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DETAIL = (ROOT / 'court' / 'detail.js').read_text(encoding='utf-8')
COURT = (ROOT / 'court' / 'court.js').read_text(encoding='utf-8')


def test_detail_uses_courthouse_alias_registry():
    assert "courthouse-aliases.json" in DETAIL
    assert "buildCourtMatcher" in DETAIL
    assert "courthouse_slug" in DETAIL


def test_detail_loads_sources_independently():
    assert "loadJson('../data/case-person-records.json'" in DETAIL
    assert "loadJson('../data/data-explorer.json'" in DETAIL
    assert "loadJson('../data/cso-cases.json'" in DETAIL
    assert "Promise.all" in DETAIL


def test_detail_accepts_list_or_object_json_shapes():
    assert "function listFrom" in DETAIL
    assert "['courthouses', 'records', 'items']" in DETAIL
    assert "data?.courthouses" in COURT


def test_empty_location_does_not_match_every_court():
    assert "if (!name && !slug) return false" in DETAIL
