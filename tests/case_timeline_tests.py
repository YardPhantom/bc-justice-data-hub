import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class CaseTimelineTests(unittest.TestCase):
 def test_page_uses_advanced_timeline(self):
  html=(ROOT/'case-timelines.html').read_text(encoding='utf-8')
  self.assertIn('data-advanced="timelines"',html)
  self.assertIn('js/advanced-page.js',html)
 def test_rich_timeline_renderer(self):
  js=(ROOT/'js/advanced-page.js').read_text(encoding='utf-8')
  for token in ('renderTimelines','case-timeline-card','Scheduled appearances, allegations and charges are not convictions','Open records'):
   self.assertIn(token,js)
 def test_export_has_case_context(self):
  py=(ROOT/'tools/advanced_features.py').read_text(encoding='utf-8')
  for token in ('court_file_number','group_concat(DISTINCT p.display_name)','group_concat(DISTINCT ch.offence_text)','daily_appearance'):
   self.assertIn(token,py)
if __name__=='__main__': unittest.main()
