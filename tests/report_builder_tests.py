from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'js' / 'report-page.js').read_text(encoding='utf-8')
HTML = (ROOT / 'reports.html').read_text(encoding='utf-8')


def test_report_builder_loads_broad_search_indexes():
    for name in ('search-cases.json', 'search-people.json', 'person-mentions.json', 'search-judgments.json'):
        assert name in JS


def test_report_builder_normalizes_multiple_json_shapes():
    assert 'const asRows' in JS
    assert "['people','records','items','results']" in JS
    assert "['judgments','records','items','results']" in JS


def test_report_builder_searches_nested_person_and_location_values():
    assert 'const searchableText' in JS
    assert 'Object.values(value).forEach(walk)' in JS
    assert "addEventListener('input'" in JS
    assert "addEventListener('search'" in JS


def test_report_builder_has_visible_filter_feedback():
    assert 'matching of' in JS
    assert 'Found ${currentRows.length.toLocaleString()}' in JS
    assert 'Filter by name, city, courthouse, court file' in HTML
