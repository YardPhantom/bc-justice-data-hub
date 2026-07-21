from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class ReviewDismissAutoApplyTests(unittest.TestCase):
 def test_editor_auto_applies_and_removes_dismissed_card(self):
  text=(ROOT/'js'/'review-editor.js').read_text(encoding='utf-8')
  self.assertIn("decision==='dismiss'",text)
  self.assertIn("/api/reviews/apply",text)
  self.assertIn("data.reviews=(data.reviews||[]).filter",text)
 def test_api_allows_dismiss_and_resolve(self):
  text=(ROOT/'tools'/'search_api.py').read_text(encoding='utf-8')
  self.assertIn("'judgment_review':{'verify','dismiss','needs_correction'}",text)
  self.assertIn("'review':{'resolve','dismiss'}",text)
  self.assertIn("data_pipeline.py'),'export'",text)
if __name__=='__main__': unittest.main()
