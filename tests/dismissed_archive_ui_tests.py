import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class DismissedArchiveUITests(unittest.TestCase):
 def test_archive_is_tucked_in_editor(self):
  html=(ROOT/'review-editor.html').read_text(encoding='utf-8')
  self.assertIn('id="dismissedArchive"',html)
  self.assertIn('<details',html)
  self.assertIn('Undo dismissal',(ROOT/'js/review-editor.js').read_text(encoding='utf-8'))
 def test_small_entry_points_exist(self):
  self.assertIn('dismissedCount',(ROOT/'review-centre.html').read_text(encoding='utf-8'))
  self.assertIn('healthDismissedCount',(ROOT/'system-health.html').read_text(encoding='utf-8'))
 def test_case_index_marks_dismissed(self):
  js=(ROOT/'js/app.js').read_text(encoding='utf-8')
  self.assertIn('Previously dismissed from review',js)
  self.assertIn('review-dismissed-archive.json',js)
 def test_restore_endpoint(self):
  api=(ROOT/'tools/search_api.py').read_text(encoding='utf-8')
  self.assertIn('/api/reviews/restore',api)
  self.assertIn('DELETE FROM dismissed_review_archive',api)
if __name__=='__main__': unittest.main()
