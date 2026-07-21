from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MaintenanceFastTests(unittest.TestCase):
    def test_normal_cmd_has_no_pause_and_uses_unbuffered_python(self):
        text = (ROOT / "tools" / "maintenance.cmd").read_text(encoding="utf-8").lower()
        self.assertNotIn("pause", text)
        self.assertIn("-u tools\\maintenance.py", text)

    def test_vacuum_is_full_mode_only(self):
        text = (ROOT / "tools" / "maintenance.py").read_text(encoding="utf-8")
        self.assertIn("if full:", text)
        self.assertIn('con.execute("VACUUM")', text)
        self.assertIn("Skipped VACUUM in normal mode", text)

    def test_duplicate_hashing_only_targets_same_size_groups(self):
        text = (ROOT / "tools" / "maintenance.py").read_text(encoding="utf-8")
        self.assertIn("by_size", text)
        self.assertIn("if len(group) < 2", text)

    def test_maintenance_reclaims_storage_and_handles_low_disk_without_copy2_crash(self):
        text = (ROOT / "tools" / "maintenance.py").read_text(encoding="utf-8")
        self.assertIn("clean_reports_temp_and_old_backups(actions, warnings)", text)
        self.assertIn("shutil.disk_usage(DB.parent).free", text)
        self.assertIn("create_backup(BACKUP_KEEP, \"maintenance\")", text)
        self.assertIn("SQLite optimization was skipped", text)
        self.assertNotIn("shutil.copy2(DB, backup)", text)

    def test_maintenance_prunes_legacy_and_partial_backups(self):
        text = (ROOT / "tools" / "maintenance.py").read_text(encoding="utf-8")
        self.assertIn("bc_justice-backup-*.db", text)
        self.assertIn("*.partial", text)
        self.assertIn("sqlite_backup_is_valid(old)", text)
        self.assertIn("PRAGMA quick_check", text)
        self.assertIn("prune_backups(BACKUP_KEEP)", text)


if __name__ == "__main__":
    unittest.main()
