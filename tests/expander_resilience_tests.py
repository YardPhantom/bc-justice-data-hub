from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_shared_layout_owns_resilient_expander_handling():
    text = (ROOT / 'js' / 'shared-layout.js').read_text(encoding='utf-8')
    assert "details.open=!details.open" in text
    assert "summary.setAttribute('aria-expanded'" in text
    assert "MutationObserver" in text
    assert "removeAllRanges" in text
    assert "if(selection)" not in text


def test_app_does_not_duplicate_header_menu_handlers():
    text = (ROOT / 'js' / 'app.js').read_text(encoding='utf-8')
    assert 'function initHeaderMenus' not in text
    assert 'initHeaderMenus();' not in text

def test_header_dropdown_arrow_rotates_clockwise_to_open():
    text = (ROOT / 'style.css').read_text(encoding='utf-8')
    assert '.nav-menu-toggle span{display:inline-block' in text
    assert 'transform-origin:center' in text
    assert '.nav-menu.open .nav-menu-toggle span{transform:rotate(-180deg)}' in text

