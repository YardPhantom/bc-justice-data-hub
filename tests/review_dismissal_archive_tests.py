import json, sqlite3, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import apply_review_actions as ara

class ReviewDismissalArchiveTests(unittest.TestCase):
 def db(self):
  c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
  c.execute("CREATE TABLE review_queue(review_id TEXT PRIMARY KEY,entity_type TEXT,entity_id TEXT,reason TEXT,severity TEXT,source_document_id TEXT,status TEXT,created_at TEXT,resolved_at TEXT,resolution_notes TEXT)")
  c.execute("CREATE TABLE published_judgments(judgment_id TEXT PRIMARY KEY,verification_state TEXT)")
  ara.setup(c); return c
 def test_dismissed_review_is_archived_and_cannot_requeue(self):
  c=self.db(); c.execute("INSERT INTO review_queue VALUES('r1','case','c1','Needs manual review','medium',NULL,'open','2026-01-01',NULL,NULL)")
  ara.apply(c,{'action_type':'review','entity_id':'r1','decision':'dismiss','notes':'not relevant'})
  row=c.execute("SELECT * FROM dismissed_review_archive WHERE review_id='r1'").fetchone()
  self.assertIsNotNone(row); self.assertEqual(row['dismissal_notes'],'not relevant')
  c.execute("DELETE FROM review_queue WHERE review_id='r1'")
  c.execute("INSERT OR IGNORE INTO review_queue VALUES('r1','case','c1','Needs manual review','medium',NULL,'open','2026-02-01',NULL,NULL)")
  self.assertEqual(c.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0],0)
 def test_judgment_dismiss_archives_all_matching_queue_rows(self):
  c=self.db(); c.execute("INSERT INTO published_judgments VALUES('j1','review')")
  c.execute("INSERT INTO review_queue VALUES('r2','published_judgment','j1','Check outcome','high',NULL,'open','2026-01-01',NULL,NULL)")
  ara.apply(c,{'action_type':'judgment_review','entity_id':'r2','target_entity_id':'j1','decision':'dismiss','notes':'false positive'})
  self.assertEqual(c.execute("SELECT COUNT(*) FROM dismissed_review_archive WHERE entity_id='j1'").fetchone()[0],1)
  self.assertEqual(c.execute("SELECT verification_state FROM published_judgments WHERE judgment_id='j1'").fetchone()[0],'dismissed')
if __name__=='__main__': unittest.main()
