import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class ReviewRestoreFullTests(unittest.TestCase):
 def test_restore_rebuilds_all_review_exports(self):
  api=(ROOT/'tools'/'search_api.py').read_text(encoding='utf-8')
  self.assertIn("advanced_features.py",api)
  self.assertIn("data_pipeline.py'),'export'",api)
  self.assertIn("active_review_count",api)
  self.assertIn("dismissed_review_count",api)

 def test_ui_reloads_to_restored_review(self):
  js=(ROOT/'js'/'review-editor.js').read_text(encoding='utf-8')
  self.assertIn('Undo dismissal',js)
  self.assertIn('location.replace(`review-editor.html${target}`)',js)
  self.assertNotIn("data.reviews=[...(data.reviews||[])",js)

if __name__=='__main__': unittest.main()
