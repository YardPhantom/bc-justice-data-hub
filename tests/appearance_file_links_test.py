from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_export_includes_local_document_path():
    text=(ROOT/'tools'/'collect_justice_sources.py').read_text(encoding='utf-8')
    assert "COALESCE(v.local_path,d.local_path,'') AS local_path" in text
    assert 'LEFT JOIN daily_court_document_versions v' in text

def test_shared_renderer_links_stored_and_official_files():
    text=(ROOT/'js'/'appearance-search.js').read_text(encoding='utf-8')
    assert 'Stored file ↗' in text
    assert 'Official file ↗' in text
    assert 'const fileLinks=r=>' in text
