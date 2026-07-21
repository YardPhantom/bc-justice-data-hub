from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class IdentityChangeDetectorTests(unittest.TestCase):
    def test_table_specific_fingerprint_ignores_statistics_only_change(self):
        mod = load_module(ROOT / "tools" / "identity_change_detector.py", "identity_change_detector_test")
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            db = temp_path / "test.db"
            conn = sqlite3.connect(db)
            conn.executescript(
                """
                CREATE TABLE people(person_id TEXT PRIMARY KEY, display_name TEXT);
                CREATE TABLE daily_appearances(appearance_id TEXT PRIMARY KEY, participant_name TEXT);
                CREATE TABLE crime_statistics(id INTEGER PRIMARY KEY, metric TEXT, value REAL);
                INSERT INTO people VALUES('p1','One Person');
                INSERT INTO daily_appearances VALUES('a1','One Person');
                INSERT INTO crime_statistics(metric,value) VALUES('rate',1.0);
                """
            )
            conn.commit()
            conn.close()
            mod.DB = db
            first = mod.snapshot_payload()

            conn = sqlite3.connect(db)
            conn.execute("UPDATE crime_statistics SET value=2.0")
            conn.commit()
            conn.close()
            second = mod.snapshot_payload()
            self.assertEqual(first["fingerprint"], second["fingerprint"])

            conn = sqlite3.connect(db)
            conn.execute("UPDATE people SET display_name='Changed Person' WHERE person_id='p1'")
            conn.commit()
            conn.close()
            third = mod.snapshot_payload()
            self.assertNotEqual(second["fingerprint"], third["fingerprint"])

    def test_detector_covers_requested_identity_inputs(self):
        mod = load_module(ROOT / "tools" / "identity_change_detector.py", "identity_change_detector_tables")
        required = {
            "people",
            "person_aliases",
            "daily_appearances",
            "cases",
            "case_people",
            "published_judgments",
            "outcomes",
            "charges",
            "cso_charges",
            "person_identity_decisions",
        }
        self.assertTrue(required.issubset(set(mod.IDENTITY_INPUT_TABLES)))


class CollectNewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cmd = (ROOT / "tools" / "collect-new.cmd").read_text(encoding="utf-8")
        cls.ps1 = (ROOT / "tools" / "collect-new.ps1").read_text(encoding="utf-8")
        cls.advanced = (ROOT / "tools" / "advanced_features.py").read_text(encoding="utf-8")
        cls.commands = (ROOT / "commands.txt").read_text(encoding="utf-8")
        cls.index = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_wait_switch_is_forwarded_and_documented(self):
        self.assertIn('"--wait" set "PS_ARGS=!PS_ARGS! -Wait"', self.cmd)
        self.assertIn("[switch]$Wait", self.ps1)
        self.assertIn("Switch: --wait", self.commands)
        self.assertIn("Switch: --wait", self.index)

    def test_identity_snapshot_and_conditional_build_are_present(self):
        self.assertIn("identity_change_detector.py snapshot", self.ps1)
        self.assertIn("identity_change_detector.py changed", self.ps1)
        self.assertIn("if ($identityChanged)", self.ps1)
        self.assertIn("Identity-related data did not change; person identity building is skipped.", self.ps1)

    def test_collection_completes_before_postprocess_launch(self):
        complete = self.ps1.index('Collection is complete.')
        launch = self.ps1.index('Start-PostProcessing -IdentityChanged')
        self.assertLess(complete, launch)
        self.assertIn("Start-Process", self.ps1)
        self.assertIn("reports\\identity-postprocess-latest.log", self.ps1)

    def test_nonidentity_advanced_profile_exists(self):
        self.assertIn("'nonidentity'", self.advanced)
        self.assertIn("stage[2] not in identity_keys", self.advanced)

    def test_status_files_are_declared(self):
        worker = (ROOT / "tools" / "identity_postprocess.py").read_text(encoding="utf-8")
        self.assertIn('post-processing-status.json', worker)
        self.assertIn('identity-postprocess-latest.log', worker)
        self.assertIn('identity-postprocess.lock', worker)
        self.assertIn('"postprocessing"', worker)


if __name__ == "__main__":
    unittest.main()
