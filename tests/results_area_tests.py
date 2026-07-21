from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_all_javascript_parses():
    import subprocess
    scripts=list((ROOT/'js').glob('*.js'))+list((ROOT/'court').glob('*.js'))
    for script in scripts:
        subprocess.run(['node','--check',str(script)],check=True,capture_output=True,text=True)

def test_map_handles_missing_and_object_shaped_data():
    text=(ROOT/'js'/'map-page.js').read_text(encoding='utf-8')
    assert 'normalizeCourts' in text
    assert 'response.ok' in text
    assert 'collect-new.cmd' in text
    assert 'esc(name)' in text

def test_relationships_include_non_cso_records():
    text=(ROOT/'js'/'relationships.js').read_text(encoding='utf-8')
    assert "appearances.forEach(row=>ensure" in text
    assert "judgments.forEach(row=>ensure" in text
    assert 'No relationship data is available' in text

def test_repeat_results_clear_on_load_failure():
    text=(ROOT/'js'/'repeat-offenders.js').read_text(encoding='utf-8')
    assert "$('repeatBody').innerHTML=''" in text
    assert "$('repeatEmpty').classList.add('show')" in text
