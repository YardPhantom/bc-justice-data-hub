#!/usr/bin/env python3
"""Create a consistent dated backup of the BC Justice SQLite database.

Uses SQLite's online backup API so the copy is valid even when WAL mode is in
use. Old automatic backups are pruned by count after a successful backup.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "database" / "bc_justice.db"
BACKUP_DIR = ROOT / "backups" / "database"
LATEST_MANIFEST = ROOT / "data" / "latest-backup.json"
DEFAULT_KEEP = 1


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def database_is_valid(path: Path) -> tuple[bool, str]:
    try:
        # sqlite3.Connection's context manager commits or rolls back but does
        # not close the connection. Explicit closing is required on Windows
        # before the backup file can be renamed or deleted.
        with closing(sqlite3.connect(path)) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()
        detail = str(result[0] if result else "No integrity result")
        return detail.lower() == "ok", detail
    except Exception as exc:  # pragma: no cover - reported to command line
        return False, str(exc)


def replace_with_retry(source: Path, destination: Path, attempts: int = 10) -> None:
    """Rename a completed backup, tolerating short Windows file locks."""
    last_error: OSError | None = None
    for attempt in range(attempts):
        try:
            source.replace(destination)
            return
        except PermissionError as exc:
            last_error = exc
            gc.collect()
            time.sleep(0.15 * (attempt + 1))
    if last_error is not None:
        raise last_error


def unlink_with_retry(path: Path, attempts: int = 6) -> None:
    """Best-effort cleanup for a temporary backup file on Windows."""
    for attempt in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            gc.collect()
            time.sleep(0.15 * (attempt + 1))


def prune_backups(keep: int) -> int:
    backups = sorted(
        BACKUP_DIR.glob("bc_justice-*.db"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for old in backups[max(keep, 1):]:
        old.unlink(missing_ok=True)
        old.with_suffix(".json").unlink(missing_ok=True)
        removed += 1
    return removed


def create_backup(keep: int, reason: str) -> int:
    started = utc_now()
    LATEST_MANIFEST.parent.mkdir(parents=True, exist_ok=True)

    if not DB_PATH.exists():
        manifest = {
            "status": "skipped",
            "reason": "Database does not exist yet",
            "requested_reason": reason,
            "created_at": started.isoformat(),
        }
        LATEST_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print("Backup skipped: database does not exist yet.")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%d-%H%M%S")
    destination = BACKUP_DIR / f"bc_justice-{stamp}.db"
    temp_destination = destination.with_suffix(".db.partial")

    try:
        # Use explicit closing: the sqlite3 context manager alone does not
        # release the Windows file handle when the block exits.
        with closing(sqlite3.connect(DB_PATH)) as source:
            with closing(sqlite3.connect(temp_destination)) as target:
                source.backup(target, pages=1000)
                target.commit()

        valid, integrity = database_is_valid(temp_destination)
        if not valid:
            raise RuntimeError(f"Backup integrity check failed: {integrity}")
        replace_with_retry(temp_destination, destination)
        removed = prune_backups(keep)
        manifest = {
            "status": "success",
            "reason": reason,
            "created_at": started.isoformat(),
            "database": str(DB_PATH.relative_to(ROOT)).replace("\\", "/"),
            "backup": str(destination.relative_to(ROOT)).replace("\\", "/"),
            "size_bytes": destination.stat().st_size,
            "integrity_check": integrity,
            "retention_count": keep,
            "old_backups_removed": removed,
        }
        destination.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        LATEST_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Database backup created: {manifest['backup']}")
        if removed:
            print(f"Removed {removed} old automatic backup(s); keeping the latest {keep}.")
        return 0
    except Exception as exc:
        unlink_with_retry(temp_destination)
        manifest = {
            "status": "failed",
            "reason": reason,
            "created_at": started.isoformat(),
            "error": str(exc),
        }
        LATEST_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"ERROR: database backup failed: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a safe local SQLite backup.")
    parser.add_argument(
        "--keep",
        type=int,
        default=int(os.environ.get("BCJUS_BACKUP_KEEP", DEFAULT_KEEP)),
        help="Number of automatic database backups to retain (default: 1).",
    )
    parser.add_argument("--reason", default="manual", help="Reason recorded in the backup manifest.")
    args = parser.parse_args()
    if args.keep < 1:
        parser.error("--keep must be at least 1")
    return create_backup(args.keep, args.reason)


if __name__ == "__main__":
    raise SystemExit(main())
