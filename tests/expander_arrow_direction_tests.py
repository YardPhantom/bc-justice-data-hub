from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_all_shared_expander_arrows_rotate_clockwise_like_header():
    css = (ROOT / "style.css").read_text(encoding="utf-8")
    assert ".nav-menu.open .nav-menu-toggle span{transform:rotate(-180deg)}" in css
    assert ".section-expander[open]>summary>.expander-arrow{transform:rotate(-180deg)}" in css
    assert ".appearance-history[open]>.appearance-count::after{transform:rotate(-135deg)" in css
    assert "rotate(180deg)" not in css
    assert "rotate(225deg)" not in css


def test_dynamic_repeat_evidence_uses_shared_circle_arrow():
    js = (ROOT / "js" / "repeat-offenders.js").read_text(encoding="utf-8")
    marker = '<span aria-hidden="true" class="expander-arrow"></span>'
    assert marker in js
