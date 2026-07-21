import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class JudgmentAutoApplyTests(unittest.TestCase):
 def test_api_has_review_apply_endpoint(self):
  text=(ROOT/'tools'/'search_api.py').read_text(encoding='utf-8')
  self.assertIn("'/api/reviews/apply'",text)
  self.assertIn("'judgment_review':{'verify','dismiss','needs_correction'}",text)
  self.assertIn("workflow_cache.py",text)
 def test_judgment_page_posts_verify_action(self):
  text=(ROOT/'js'/'source-page.js').read_text(encoding='utf-8')
  self.assertIn("/api/reviews/apply",text)
  self.assertIn("Automatic apply unavailable",text)
  self.assertIn("location.reload()",text)
if __name__=='__main__': unittest.main()
