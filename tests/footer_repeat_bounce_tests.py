from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class FooterRepeatBounceTests(unittest.TestCase):
    def test_repeat_offenders_footer_pill_only_bounces_on_interaction(self):
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        self.assertNotIn(".repeat-footer-pill{animation:", css)
        self.assertIn(".repeat-footer-pill:hover,.repeat-footer-pill:focus-visible{animation:header-pill-bounce .48s ease}", css)

if __name__ == "__main__":
    unittest.main()
