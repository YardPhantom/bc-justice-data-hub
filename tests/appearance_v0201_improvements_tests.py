from pathlib import Path
import importlib.util, json, sqlite3

ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/'js'/'appearance-search.js').read_text(encoding='utf-8')
CSS=(ROOT/'style.css').read_text(encoding='utf-8')


def test_date_shortcuts_active_filters_and_url_state():
    for token in ('data-date-shortcut="today"','data-date-shortcut="next7"','data-date-shortcut="past30"','data-date-shortcut="all"','data-active-filters','data-clear-filter','URL_FILTER_KEYS','history[mode===\'push\'?\'pushState\':\'replaceState\']','window.addEventListener(\'popstate\''):
        assert token in JS


def test_compact_detailed_grouping_charge_badges_and_sticky_controls():
    for token in ('data-view="compact"','data-view="detailed"','data-group-file','groupByFile?\'file\':\'\'','courtFileGroupMarkup','appearance-charge-badge','data-page-size-top','appearance-results-toolbar'):
        assert token in JS
    assert '.appearance-results-toolbar{position:sticky' in CSS
    assert '@media(max-width:760px)' in CSS
    assert '.appearance-results-table tr{display:block' in CSS


def test_people_index_is_lazy_and_api_metadata_is_used():
    assert "Promise.all([loadStaticRecords(),loadPeopleData()])" in JS
    assert 'person_profile_id' in JS
    assert 'identity_match_count' in JS
    assert 'Open person profile' in JS


MOD=ROOT/'tools'/'search_api.py'
spec=importlib.util.spec_from_file_location('search_api_v0201',MOD)
api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)


def make_db():
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.executescript(api.APPEARANCE_CACHE_SCHEMA)
    c.execute('CREATE TABLE search_records(record_id TEXT,entity_type TEXT,title TEXT,names TEXT,record_status TEXT,payload_json TEXT,indexed_at TEXT)')
    person={'id':'person-1','type':'person','title':'SMITH, JOHN','names':['SMITH, JOHN','John Smith'],'record_status':'current'}
    c.execute('INSERT INTO search_records VALUES(?,?,?,?,?,?,?)',('person:1','person','SMITH, JOHN','SMITH, JOHN | John Smith','current',json.dumps(person),'2026-07-21'))
    records=[
      {'appearance_id':'a1','participant_name':'SMITH, JOHN','court_file_number':'123-45','courthouse_name':'Vancouver','list_date':'2026-07-21','appearance_time':'09:00','charge_confidence':'Confirmed'},
      {'appearance_id':'a2','participant_name':'SMITH, JOHN','court_file_number':'123-45','courthouse_name':'Vancouver','list_date':'2026-07-20','appearance_time':'10:00','charge_confidence':'Likely'},
      {'appearance_id':'a3','participant_name':'DOE, JANE','court_file_number':'999-00','courthouse_name':'Victoria','list_date':'2026-07-19','appearance_time':'11:00','charge_confidence':'Possible'},
    ]
    for r in records:
      c.execute('INSERT INTO appearance_search_records VALUES(?,?,?,?,?,?,?,?,?,?)',(r['appearance_id'],r['participant_name'],api.appearance_norm(r['participant_name']),r['court_file_number'],api.appearance_file_norm(r['court_file_number']),r['courthouse_name'],r['list_date'],r['charge_confidence'],json.dumps(r),'2026-07-21'))
    api.PERSON_LOOKUP_CACHE={'signature':None,'records':{}}
    return c


def test_api_returns_person_profile_metadata_and_court_file_groups():
    c=make_db()
    normal=api.search_appearances(c,{'name':['smith'],'limit':['50'],'offset':['0']})
    assert normal['records'][0]['person_profile_id']=='person-1'
    assert normal['records'][0]['identity_match_count']==1
    assert normal['records'][0]['identity_review_required'] is False
    grouped=api.search_appearances(c,{'group':['file'],'limit':['50'],'offset':['0']})
    assert grouped['grouped'] is True
    assert grouped['total']==2
    first=next(r for r in grouped['records'] if r['court_file_number']=='123-45')
    assert first['group_count']==2
    assert len(first['grouped_appearances'])==2
