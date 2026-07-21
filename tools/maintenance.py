from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import shutil
import sqlite3

from backup_database import BACKUP_DIR, create_backup, prune_backups

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "database" / "bc_justice.db"
REPORTS = ROOT / "reports"
IMPORTS = ROOT / "imports"
BACKUP_KEEP = 1
MIN_BACKUP_MARGIN = 64 * 1024 * 1024
MAX_BACKUP_MARGIN = 512 * 1024 * 1024


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def format_bytes(value: int) -> str:
    amount = float(max(value, 0))
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "bytes" else f"{int(amount)} bytes"
        amount /= 1024
    return f"{int(value)} bytes"


def remove_path(path: Path, actions: list[str], warnings: list[str], label: str) -> None:
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
        actions.append(label)
    except OSError as exc:
        warnings.append(f"Could not remove {path.relative_to(ROOT)}: {exc}")


def sqlite_backup_is_valid(path: Path) -> bool:
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=10)) as con:
            result = con.execute("PRAGMA quick_check").fetchone()
        return bool(result and str(result[0]).lower() == "ok")
    except (OSError, sqlite3.DatabaseError, ValueError):
        return False


def clean_reports_temp_and_old_backups(actions: list[str], warnings: list[str]) -> None:
    print("[1/4] Reclaiming safe temporary and old-backup storage...", flush=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    reports = sorted(REPORTS.glob("collection-run-*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in reports[30:]:
        remove_path(path, actions, warnings, f"Removed old report {path.name}")

    for folder in [IMPORTS / "tmp", IMPORTS / "temp", IMPORTS / "cache"]:
        if folder.exists():
            remove_path(folder, actions, warnings, f"Removed {folder.relative_to(ROOT)}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for partial in BACKUP_DIR.glob("*.partial"):
        remove_path(partial, actions, warnings, f"Removed incomplete backup {partial.name}")

    try:
        removed = prune_backups(BACKUP_KEEP)
        if removed:
            actions.append(f"Removed {removed} old automatic database backup(s)")
    except OSError as exc:
        warnings.append(f"Could not prune automatic database backups: {exc}")

    # Older maintenance releases copied backups beside the live database and
    # never pruned them. Preserve one only when no managed backup exists; after
    # a successful managed backup, the remaining legacy copy is removed.
    legacy = sorted(
        DB.parent.glob("bc_justice-backup-*.db"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ) if DB.parent.exists() else []
    managed_exists = any(BACKUP_DIR.glob("bc_justice-*.db"))
    legacy_keeper: Path | None = None
    for old in legacy:
        if managed_exists:
            remove_path(old, actions, warnings, f"Removed old legacy database backup {old.name}")
            continue
        if legacy_keeper is None and sqlite_backup_is_valid(old):
            legacy_keeper = old
            continue
        label = (
            f"Removed incomplete legacy database backup {old.name}"
            if legacy_keeper is None
            else f"Removed old legacy database backup {old.name}"
        )
        remove_path(old, actions, warnings, label)


def backup_capacity() -> tuple[bool, int, int]:
    if not DB.exists():
        return False, 0, 0
    database_size = DB.stat().st_size
    margin = min(MAX_BACKUP_MARGIN, max(MIN_BACKUP_MARGIN, database_size // 20))
    required = database_size + margin
    free = shutil.disk_usage(DB.parent).free
    return free >= required, free, required


def create_maintenance_backup(actions: list[str], warnings: list[str]) -> bool:
    if not DB.exists():
        warnings.append("Database file not found; SQLite maintenance was skipped")
        return False

    print("[2/4] Creating validated database backup...", flush=True)
    enough_space, free, required = backup_capacity()
    if not enough_space:
        warnings.append(
            "Database backup and SQLite optimization were skipped because the disk has "
            f"{format_bytes(free)} free; approximately {format_bytes(required)} is required. "
            "Safe storage cleanup still completed."
        )
        return False

    if create_backup(BACKUP_KEEP, "maintenance") != 0:
        warnings.append(
            "Database backup could not be completed; SQLite optimization was skipped. "
            "Safe storage cleanup still completed."
        )
        return False

    actions.append("Created and integrity-checked the maintenance database backup")

    # A managed backup now exists, so the old unbounded maintenance-copy format
    # is no longer needed.
    for old in DB.parent.glob("bc_justice-backup-*.db"):
        remove_path(old, actions, warnings, f"Removed legacy database backup {old.name}")
    return True


def database_maintenance(actions: list[str], warnings: list[str], full: bool) -> None:
    if not create_maintenance_backup(actions, warnings):
        return

    print("[3/4] Checking and optimizing SQLite...", flush=True)
    con = sqlite3.connect(DB, timeout=60)
    try:
        issues = con.execute("PRAGMA integrity_check").fetchone()[0]
        if issues != "ok":
            warnings.append(f"Database integrity: {issues}")
        con.execute("PRAGMA optimize")
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.DatabaseError:
            pass
        con.commit()
        actions.append("Checked and optimized SQLite")

        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for required in ["catalogue_resources", "import_runs", "review_queue"]:
            if required not in tables:
                warnings.append(f"Missing expected table: {required}")

        if full:
            print("[3/4] Full mode: compacting SQLite database. This can take a long time...", flush=True)
            con.execute("VACUUM")
            con.commit()
            actions.append("Vacuumed SQLite in full-maintenance mode")
        else:
            actions.append("Skipped VACUUM in normal mode; use --full for database compaction")
    finally:
        con.close()


def remove_exact_duplicates(actions: list[str], warnings: list[str], full: bool) -> None:
    catalogue = IMPORTS / "catalogue"
    if not catalogue.exists():
        actions.append("No downloaded catalogue folder to scan")
        return

    files = [path for path in catalogue.iterdir() if path.is_file()]
    by_size: dict[int, list[Path]] = defaultdict(list)
    for path in files:
        try:
            by_size[path.stat().st_size].append(path)
        except OSError as exc:
            warnings.append(f"Could not inspect {path.name}: {exc}")

    candidates = [path for group in by_size.values() if len(group) > 1 for path in group]
    if not candidates:
        actions.append("No same-size downloaded resources needed duplicate hashing")
        return

    if not full and len(candidates) > 250:
        actions.append(
            f"Deferred duplicate hashing for {len(candidates)} same-size files; use --full to scan them"
        )
        return

    print(f"[4/4] Checking {len(candidates)} possible duplicate downloads...", flush=True)
    removed = 0
    for group in by_size.values():
        if len(group) < 2:
            continue
        seen: dict[str, Path] = {}
        ordered = sorted(group, key=lambda p: p.stat().st_mtime, reverse=True)
        for path in ordered:
            try:
                key = digest(path)
            except OSError as exc:
                warnings.append(f"Could not hash {path.name}: {exc}")
                continue
            if key in seen:
                path.unlink()
                removed += 1
            else:
                seen[key] = path
    actions.append(f"Removed {removed} exact duplicate downloaded resources")


def validate_manager(warnings: list[str]) -> None:
    manager = ROOT / "data" / "data-manager.json"
    if not manager.exists():
        return
    try:
        data = json.loads(manager.read_text(encoding="utf-8"))
        for resource in data.get("resources", []):
            local_path = resource.get("local_path")
            if local_path and not (ROOT / local_path).exists():
                warnings.append(f"Missing local file: {local_path}")
            if not resource.get("url"):
                warnings.append(
                    f"Resource without source URL: {resource.get('name') or resource.get('resource_id')}"
                )
    except Exception as exc:
        warnings.append(f"Could not validate data-manager.json: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Maintain the BC Justice Data Hub database and storage.")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run slow SQLite VACUUM and exhaustive duplicate-file hashing.",
    )
    args = parser.parse_args()

    actions: list[str] = []
    warnings: list[str] = []
    mode = "full" if args.full else "normal"
    print(f"BC Justice maintenance starting ({mode} mode)...", flush=True)

    clean_reports_temp_and_old_backups(actions, warnings)
    database_maintenance(actions, warnings, args.full)
    remove_exact_duplicates(actions, warnings, args.full)
    validate_manager(warnings)

    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    text = stamp + "\n" + "\n".join("OK: " + action for action in actions)
    if warnings:
        text += "\n" + "\n".join("WARNING: " + warning for warning in warnings)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "maintenance-latest.txt").write_text(text, encoding="utf-8")

    print("Maintenance complete:")
    for action in actions:
        print(" - " + action)
    for warning in warnings:
        print(" ! " + warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
