from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]


def test_courthouse_appearances_are_paginated_at_50():
    page = BeautifulSoup((ROOT / 'court' / 'detail.html').read_text(encoding='utf-8'), 'html.parser')
    pager = page.find(id='appearancePagination')
    assert pager is not None
    assert pager.find(id='appearancePrev') is not None
    assert pager.find(id='appearanceNext') is not None
    assert pager.find_previous('div', class_='table-wrap').find(id='appearanceBody') is not None
    script = (ROOT / 'court' / 'detail.js').read_text(encoding='utf-8')
    assert 'const appearancePageSize = 50' in script
    assert 'allAppearances.slice(startIndex, startIndex + appearancePageSize)' in script
    assert "label.textContent = `Showing ${first.toLocaleString()}–${last.toLocaleString()}" in script


def test_collect_new_skip_backup_switch_is_forwarded_and_documented():
    cmd = (ROOT / 'tools' / 'collect-new.cmd').read_text(encoding='utf-8')
    ps1 = (ROOT / 'tools' / 'collect-new.ps1').read_text(encoding='utf-8')
    commands = (ROOT / 'commands.txt').read_text(encoding='utf-8')
    homepage = (ROOT / 'index.html').read_text(encoding='utf-8')
    assert '"--skip-backup"' in cmd
    assert '-SkipBackup' in cmd
    assert '[switch]$SkipBackup' in ps1
    assert "Backup skipped by --skip-backup." in ps1
    assert 'Switch: --skip-backup' in commands
    assert 'Switch: --skip-backup' in homepage


def test_homepage_status_gradient_and_card_bounce():
    page = BeautifulSoup((ROOT / 'index.html').read_text(encoding='utf-8'), 'html.parser')
    assert 'home-page' in page.body.get('class', [])
    assert 'People are innocent until proven guilty in Canada.' in page.get_text(' ', strip=True)
    css = (ROOT / 'style.css').read_text(encoding='utf-8')
    assert 'background:linear-gradient(135deg,var(--bg) 0%' in css
    assert '.home-page article:hover,.home-page article:focus-within{animation:header-pill-bounce .48s ease' in css
