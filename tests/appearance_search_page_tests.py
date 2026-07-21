from pathlib import Path
ROOT=Path(__file__).parents[1]

def test_appearance_search_uses_shared_renderer_and_starts_empty():
    page=(ROOT/'appearance-search.html').read_text(encoding='utf-8')
    home=(ROOT/'index.html').read_text(encoding='utf-8')
    js=(ROOT/'js'/'appearance-search.js').read_text(encoding='utf-8')
    assert 'data-appearance-search-renderer' in page
    assert 'data-appearance-search-renderer' in home
    assert "if(!active)" in js
    assert 'daily-court-lists-page-' in js

def test_appearance_search_has_api_pagination_filters_and_history():
    js=(ROOT/'js'/'appearance-search.js').read_text(encoding='utf-8')
    for token in (
        'data-appearance-match',
        'data-appearance-from',
        'data-appearance-to',
        'data-appearance-confidence',
        'data-appearance-sort',
        'Newest appearance',
        'Oldest appearance',
        'Name A–Z',
        'Courthouse A–Z',
        'Charge confidence — strongest first',
        'Most catalogued appearances',
        'Exact full name',
        'Partial name',
        'Appearance history',
        'catalogued appearances',
        '/api/appearances?',
        '/api/appearances/history',
        'Static JSON fallback',
        'data-page-prev',
        'data-page-next',
        'data-page-size',
        '<option value="50">50</option>',
        '<option value="100">100</option>',
    ):
        assert token in js
    assert "filters.match==='exact'?recordName===name:recordName.includes(name)" in js
    assert "(!filters.from||date>=filters.from)&&(!filters.to||date<=filters.to)" in js
    assert "confidenceLabel(r)===filters.confidence" in js
    assert 'limit:1000' in js  # full-result exports page through the API
    assert 'if(name&&typedLength<2)' in js
    assert "typedLength<2&&!filters.court" not in js
    assert "if(filters.sort)p.set('sort',filters.sort)" in js
    assert "sortInput.value='newest'" in js
    assert 'searchSerial++;nameInput.value' in js
    assert 'const requestFallback=async error=>' in js
    assert 'provider=await getFallback()' not in js

def test_appearance_static_json_uses_conditional_browser_cache():
    js=(ROOT/'js'/'appearance-search.js').read_text(encoding='utf-8')
    assert "const STATIC_JSON_CACHE='no-cache'" in js
    assert "cache:options.cache??STATIC_JSON_CACHE" in js
    assert "apiJson('/api/appearances/facets'" in js
    assert "{cache:'no-store',signal:ctrl.signal}" in js
    assert "getJson('data/daily-court-lists.json')" in js
    assert "getJson(`data/daily-court-lists-page-${i+2}.json`)" in js



def test_appearance_export_pills_are_hidden_until_results_and_centered_below_table():
    js=(ROOT/'js'/'appearance-search.js').read_text(encoding='utf-8')
    css=(ROOT/'style.css').read_text(encoding='utf-8')
    filters_at=js.index('appearance-filters appearance-filters-extended')
    table_at=js.index('appearance-results-table',filters_at)
    pagination_at=js.index('appearance-pagination',table_at)
    exports_at=js.index('appearance-export-row',pagination_at)
    empty_at=js.index('data-appearance-empty',exports_at)
    assert filters_at < table_at < pagination_at < exports_at < empty_at
    assert 'data-appearance-export aria-label="Appearance Search export options" hidden' in js
    assert 'setExportAvailable(false)' in js
    assert 'setExportAvailable(total>0)' in js
    assert 'exportRow.hidden=!available' in js
    assert '.appearance-export-row{display:flex;width:100%' in css
    assert '.appearance-export-row[hidden]{display:none}' in css
    assert 'justify-content:center' in css


def test_appearance_form_renders_before_background_data_and_api_warmup():
    js=(ROOT/'js'/'appearance-search.js').read_text(encoding='utf-8')
    init_at=js.index('function init()')
    fallback_at=js.index('const getFallback=',init_at)
    mount_at=js.index('controllers=hosts.map(host=>mountSearch',fallback_at)
    court_at=js.index('loadCourtData()',mount_at)
    warm_at=js.index('scheduleBackground(()=>scheduleRecovery())',court_at)
    recovery_at=js.index('const readiness=await wakeAndWaitForApi()',init_at)
    facets_at=js.index("apiJson('/api/appearances/facets'",recovery_at)
    assert init_at < fallback_at < mount_at < court_at < warm_at
    assert recovery_at < facets_at
    assert "host.innerHTML=markup()" in js
    assert "Search fields ready" in js
    assert "requestIdleCallback" in js
    assert "getJson('data/courthouses.json')" in js
    # The full people index is loaded only if the API fails and static fallback is needed.
    assert "Promise.all([loadStaticRecords(),loadPeopleData()])" in js
    assert "loadPeopleData()\n      .then" not in js


def test_appearance_facets_are_cached_and_static_fallback_remains_lazy():
    js=(ROOT/'js'/'appearance-search.js').read_text(encoding='utf-8')
    for token in (
        "FACETS_CACHE_KEY='bcjus.appearance.facets.v1'",
        'readCachedFacets()',
        'writeCachedFacets(facets)',
        'localStorage.getItem(FACETS_CACHE_KEY)',
        'localStorage.setItem(FACETS_CACHE_KEY',
        'const getFallback=()=>fallbackPromise||(fallbackPromise=Promise.all([loadStaticRecords(),loadPeopleData()])',
        "kind:'api'",
        "kind:'static'",
    ):
        assert token in js
    init_at=js.index('function init()')
    fallback_definition=js.index('const getFallback=',init_at)
    mount_at=js.index('controllers=hosts.map',fallback_definition)
    assert fallback_definition < mount_at
    assert 'provider=await getFallback()' not in js
    assert 'const fallback=await getFallback()' in js

def test_appearance_notice_is_in_intro_without_separate_warning_line():
    page=(ROOT/'appearance-search.html').read_text(encoding='utf-8')
    home=(ROOT/'index.html').read_text(encoding='utf-8')
    js=(ROOT/'js'/'appearance-search.js').read_text(encoding='utf-8')
    intro='Search people who were or are scheduled to appear by name, courthouse, or date. Older appearances remain catalogued as new lists are collected. A scheduled appearance is not a conviction and does not prove an allegation. It does not mean this person was at court that day.'
    assert intro in page
    assert intro in home
    assert 'appearance-page-warning' not in page
    markup=js[js.index('const markup=()=>'):js.index('const STATIC_JSON_CACHE')]
    assert 'A scheduled appearance is not a conviction' not in markup



def test_bottom_pagination_does_not_duplicate_page_size_control():
    js=(ROOT/'js'/'appearance-search.js').read_text(encoding='utf-8')
    pagination_start=js.index('<div class="appearance-pagination"')
    pagination_end=js.index('</div>',pagination_start)
    pagination_markup=js[pagination_start:pagination_end]
    assert 'data-page-size' not in pagination_markup
    assert js.count('data-page-size-top') >= 1
    assert "pageSizeInputs=$$('[data-page-size-top]')" in js
