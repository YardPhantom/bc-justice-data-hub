from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / 'js' / 'search-service.js').read_text(encoding='utf-8')
PAGE = (ROOT / 'js' / 'search-page.js').read_text(encoding='utf-8')


def test_missing_single_json_index_does_not_break_all_record_search():
    assert 'Promise.allSettled' in SERVICE
    assert "if(!groups.length)throw Error('Search indexes unavailable')" in SERVICE


def test_zero_result_live_search_falls_back_to_json_indexes():
    assert "if(!query||Number(live.total||0)>0)return live" in SERVICE


def test_simple_person_name_queries_show_each_record_separately():
    assert "nameQuery=/^[a-z][a-z'’.-]*" in PAGE
    assert "group:nameQuery?'false':'true'" in PAGE
    assert 'Showing each matching record separately' in PAGE
