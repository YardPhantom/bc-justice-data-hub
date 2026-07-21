import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class DatasetManagerActionTests(unittest.TestCase):
    def test_manager_has_action_column_and_routes(self):
        html=(ROOT/'index.html').read_text(encoding='utf-8')
        js=(ROOT/'js'/'app.js').read_text(encoding='utf-8')
        self.assertIn('<th>Action</th>', html)
        for target in ['review-editor.html?','retry-centre.html?','source-validation.html?','duplicate-review.html?','pdf-corrections.html?']:
            self.assertIn(target, js)
        self.assertIn("label:'View records'", js)

    def test_destination_pages_accept_manager_parameters(self):
        self.assertIn("params.get('resource')", (ROOT/'js'/'retry-centre.js').read_text(encoding='utf-8'))
        self.assertIn("validationParams.get('source')", (ROOT/'js'/'source-validation.js').read_text(encoding='utf-8'))
        self.assertIn("pageParams.get('resource')", (ROOT/'js'/'advanced-page.js').read_text(encoding='utf-8'))

if __name__=='__main__': unittest.main()
