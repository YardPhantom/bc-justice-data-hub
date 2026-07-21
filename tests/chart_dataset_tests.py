from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_three_nested_chart_expanders():
    html=(ROOT/'index.html').read_text(encoding='utf-8')
    for ident in ('courtActivityChart','verifiedOutcomesChart','crimeSeverityChart'):
        assert f'id="{ident}"' in html
    assert 'Indexed case and court-list categories' not in html

def test_chart_data_preserves_status_boundaries():
    source=(ROOT/'tools'/'data_pipeline.py').read_text(encoding='utf-8')
    assert "verification_state,''))='verified'" in source
    assert "allowed=('convicted','acquitted','stayed','dismissed','withdrawn')" in source
    assert "COALESCE(is_current,1)=1" in source
    assert 'court-list appearances are not charges or convictions' in source

def test_frontend_loads_each_chart_dataset():
    app=(ROOT/'js'/'app.js').read_text(encoding='utf-8')
    for key in ('courtActivity','verifiedOutcomes','crimeSeverity'):
        assert key in app
    assert 'renderJusticeCharts()' in app
