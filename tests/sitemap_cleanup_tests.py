from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]


def test_sitemap_matches_current_homepage_groups_and_search_tools():
    page = BeautifulSoup((ROOT / 'sitemap.html').read_text(encoding='utf-8'), 'html.parser')
    headings = [h.get_text(' ', strip=True) for h in page.select('.sitemap-group h2')]
    assert headings == [
        'Search & People',
        'Daily Justice Overview',
        'Cases, Judgments & Review',
        'Crime Statistics',
        'Admin System',
    ]
    hrefs = {a.get('href') for a in page.select('.sitemap-links a[href]')}
    for href in ('appearance-search.html', 'index.html#fullSearch', 'search.html', 'repeat-offenders.html'):
        assert href in hrefs


def test_sitemap_links_every_standalone_page_that_does_not_require_a_query():
    page = BeautifulSoup((ROOT / 'sitemap.html').read_text(encoding='utf-8'), 'html.parser')
    linked = {a.get('href', '').split('#')[0] for a in page.select('.sitemap-links a[href]')}
    excluded = {'sitemap.html', 'court/detail.html'}
    html_pages = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob('*.html')
        if path.relative_to(ROOT).as_posix() not in excluded
    }
    assert html_pages <= linked | {'index.html'}


def test_removed_homepage_and_warning_selectors_are_cleaned_up():
    css = (ROOT / 'style.css').read_text(encoding='utf-8')
    assert '#reportsMonitoring' not in css
    assert '#qualityGovernance' not in css
    assert '.appearance-page-warning' not in css
    assert css.count('.manager-action{') == 1
