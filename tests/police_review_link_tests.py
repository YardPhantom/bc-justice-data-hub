from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class PoliceReviewLinkTests(unittest.TestCase):
    def test_review_state_links_to_manual_review(self):
        text=(ROOT / "js" / "police-page.js").read_text(encoding="utf-8")
        self.assertIn("review-editor.html?q=", text)
        self.assertIn("Open review", text)
        self.assertIn("police-review-link", text)

if __name__ == "__main__":
    unittest.main()
