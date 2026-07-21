import sqlite3
import tempfile
import unittest
from pathlib import Path


class DataPipelineExportTests(unittest.TestCase):
    def test_export_initializes_current_table_names(self):
        source = (Path(__file__).parents[1] / 'tools' / 'data_pipeline.py').read_text(encoding='utf-8')
        export_body = source.split('def export(c):', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('tables_now={r[0] for r in c.execute', export_body)
        self.assertLess(export_body.index('tables_now='), export_body.index("if 'daily_appearances' in tables_now"))


if __name__ == '__main__':
    unittest.main()
