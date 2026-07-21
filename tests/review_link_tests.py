from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_case_person_index_has_review_links():
    app = (ROOT / "js" / "app.js").read_text(encoding="utf-8")
    assert "function reviewLink(r)" in app
    assert "review-editor.html?review=" in app
    assert "review-editor.html?q=" in app
    assert "Review item" in app
    assert "Find in Review Editor" in app

def test_review_editor_accepts_targeted_query():
    script = (ROOT / "js" / "review-editor.js").read_text(encoding="utf-8")
    assert "params.get('q')" in script
