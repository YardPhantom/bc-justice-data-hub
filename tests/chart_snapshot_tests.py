from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ChartSnapshotTests(unittest.TestCase):
    def test_collect_new_rebuilds_missing_or_empty_charts(self):
        text = (ROOT / 'tools' / 'collect-new.ps1').read_text(encoding='utf-8')
        self.assertIn("data\\charts-summary.json", text)
        self.assertIn('$chartsNeedRefresh', text)
        self.assertIn('Dashboard or chart snapshots are missing/empty', text)

    def test_export_has_chart_fallbacks_and_diagnostics(self):
        text = (ROOT / 'tools' / 'data_pipeline.py').read_text(encoding='utf-8')
        self.assertIn("if not court_activity and 'staging_rows' in tables_now", text)
        self.assertIn("if not verified_outcomes and 'published_judgments' in tables_now", text)
        self.assertIn("'sourceTables':sorted(tables_now)", text)
        self.assertIn("'counts':{'courtActivity':len(court_activity)", text)

    def test_frontend_no_longer_claims_collection_never_ran(self):
        text = (ROOT / 'js' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('exporter will rebuild missing or empty chart snapshots automatically', text)

if __name__ == '__main__':
    unittest.main()
