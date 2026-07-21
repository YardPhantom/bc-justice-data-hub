from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]


def test_homepage_uses_new_categories_and_merged_statistics_cards():
    page = BeautifulSoup((ROOT / 'index.html').read_text(encoding='utf-8'), 'html.parser')
    groups = [(item.get('id'), item.summary.get_text(' ', strip=True)) for item in page.select('details.main-expander')]
    assert groups == [
        ('searchPeople', 'Search & People'),
        ('dailyJustice', 'Daily Justice Overview'),
        ('caseJudgmentTools', 'Cases, Judgments & Review'),
        ('crimeStats', 'Crime Statistics'),
        ('adminSystem', 'Admin System'),
    ]
    assert page.find(id='statisticsTools') is None
    dashboard_links = {a.get('href') for a in page.select('#justiceDashboards .domain-grid a[href]')}
    for href in ('police-data.html', 'statcan-crime.html', 'prosecution.html', 'corrections-oversight.html', 'comparisons.html', 'map.html'):
        assert href in dashboard_links
    admin = page.find(id='adminSystem')
    for child_id in ('reportMonitoringTools', 'recentChanges', 'sources', 'governanceTools', 'dataManager', 'systemStatusTools', 'imports', 'commandsPanel'):
        assert admin.find(id=child_id) is not None


def test_case_and_explorer_tables_are_paged_at_50_rows():
    page = BeautifulSoup((ROOT / 'index.html').read_text(encoding='utf-8'), 'html.parser')
    for prefix in ('records', 'explorer'):
        pager = page.find(id=f'{prefix}Pagination')
        assert pager is not None
        assert pager.find(id=f'{prefix}Prev') is not None
        assert pager.find(id=f'{prefix}Next') is not None
        table = page.find(id='recordsBody' if prefix == 'records' else 'explorerBody').find_parent('div', class_='table-wrap')
        assert pager.find_previous('div', class_='table-wrap') == table
    script = (ROOT / 'js' / 'app.js').read_text(encoding='utf-8')
    assert 'const HOME_PAGE_SIZE=50' in script
    assert "types:'case,person'" in script
    assert "limit:Math.max(1,needed)" in script
    assert "localVisible=local.slice(pageOffset,pageOffset+HOME_PAGE_SIZE)" in script
    assert "visible=rows.slice(start,start+HOME_PAGE_SIZE)" in script
    assert "updateHomePager('records'" in script
    assert "updateHomePager('explorer'" in script


def test_header_and_sitemap_use_crime_statistics_and_admin_system():
    shared = (ROOT / 'js' / 'shared-layout.js').read_text(encoding='utf-8')
    assert '>Crime Statistics <' in shared
    assert '>Admin System <' in shared
    for stale in ('Justice Statistics', 'Reports &amp; Governance', 'System &amp; Maintenance', '#reportsGovernance', '#systemMaintenance'):
        assert stale not in shared
    for path in ROOT.rglob('*.html'):
        page = BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser')
        labels = [button.get_text(' ', strip=True).replace('⌄', '').strip() for button in page.select('.nav-menu-toggle')]
        assert labels == ['Daily Justice', 'Cases & Review', 'Crime Statistics', 'Admin System'], path


def test_commands_are_synchronized_and_switches_are_documented():
    menu = (ROOT / 'command.cmd').read_text(encoding='utf-8')
    commands = (ROOT / 'commands.txt').read_text(encoding='utf-8')
    page = BeautifulSoup((ROOT / 'index.html').read_text(encoding='utf-8'), 'html.parser')
    on_page = page.select_one('#commandsPanel pre.commands-list').get_text()
    for command in (
        'tools\\install-search-helper.cmd',
        'tools\\search_api.py',
        'tools\\search_supervisor.py',
        'tools\\collect_statcan_crime.py --refresh-large',
        'tools\\data_pipeline.py export',
        'tools\\maintenance.cmd --full',
    ):
        assert command in menu or command in commands
    assert 'Switch: --quick' in commands
    assert 'Switch: --force' in commands
    assert 'Switch: --idle-timeout SECONDS' in commands
    assert on_page.strip() == commands.strip()


def test_csv_json_file_button_uses_primary_pill_styling():
    page = BeautifulSoup((ROOT / 'index.html').read_text(encoding='utf-8'), 'html.parser')
    chooser = page.find(id='fileInput')
    assert 'pill-file-input' in chooser.get('class', [])
    css = (ROOT / 'style.css').read_text(encoding='utf-8')
    assert '.pill-file-input::file-selector-button' in css
    assert 'background:var(--blue)' in css
