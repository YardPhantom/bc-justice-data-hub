#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "database" / "bc_justice.db"
CACHE_DIR = ROOT / "database" / ".workflow-cache"

IDENTITY_INPUT_TABLES = (
    "people",
    "person_aliases",
    "person_mentions",
    "daily_appearances",
    "cases",
    "case_people",
    "published_judgments",
    "outcomes",
    "charges",
    "cso_case_files",
    "cso_charges",
    "appearance_case_links",
    "person_identity_decisions",
    "review_actions",
)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def state_path(name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    return CACHE_DIR / f"{safe}.identity-snapshot.json"


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def encode_value(value):
    if value is None:
        return ["null", None]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, float):
        return ["float", repr(value)]
    if isinstance(value, int):
        return ["int", value]
    return ["text", str(value)]


def connect_read_only() -> sqlite3.Connection:
    uri = f"file:{DB.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def table_signature(conn: sqlite3.Connection, table: str) -> dict:
    exists = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return {"exists": False, "rows": 0, "sha256": None}

    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({quote_ident(table)})")]
    digest = hashlib.sha256()
    digest.update(json.dumps(columns, ensure_ascii=False).encode("utf-8"))

    order_columns = [
        row[1]
        for row in sorted(
            conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall(),
            key=lambda row: row[5] or 999,
        )
        if row[5]
    ]
    sql_text = str(exists[0] or "").upper()
    if order_columns:
        order_sql = ",".join(quote_ident(c) for c in order_columns)
    elif "WITHOUT ROWID" not in sql_text:
        order_sql = "rowid"
    else:
        order_sql = ",".join(quote_ident(c) for c in columns)

    row_count = 0
    query = f"SELECT * FROM {quote_ident(table)} ORDER BY {order_sql}"
    for row in conn.execute(query):
        payload = [encode_value(row[col]) for col in columns]
        digest.update(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
        row_count += 1
    return {"exists": True, "rows": row_count, "sha256": digest.hexdigest()}


def snapshot_payload() -> dict:
    if not DB.exists():
        return {"generatedAt": now(), "databaseExists": False, "tables": {}}
    with connect_read_only() as conn:
        tables = {table: table_signature(conn, table) for table in IDENTITY_INPUT_TABLES}
    combined = hashlib.sha256(
        json.dumps(tables, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "generatedAt": now(),
        "databaseExists": True,
        "database": str(DB),
        "fingerprint": combined,
        "tables": tables,
    }


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect changes to database tables that feed person-identity rebuilding."
    )
    parser.add_argument("command", choices=("snapshot", "changed", "current", "clear"))
    parser.add_argument("--name", default="collect-new")
    args = parser.parse_args()
    path = state_path(args.name)

    if args.command == "clear":
        path.unlink(missing_ok=True)
        print(json.dumps({"cleared": True, "path": str(path)}))
        return 0

    current = snapshot_payload()
    if args.command == "snapshot":
        write_json_atomic(path, current)
        print(json.dumps({"snapshot": True, "fingerprint": current.get("fingerprint"), "tables": current.get("tables", {})}, indent=2))
        return 0

    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        previous = {}

    changed_tables = []
    previous_tables = previous.get("tables") or {}
    current_tables = current.get("tables") or {}
    for table in IDENTITY_INPUT_TABLES:
        if previous_tables.get(table) != current_tables.get(table):
            changed_tables.append(table)

    changed = not previous or previous.get("fingerprint") != current.get("fingerprint")
    result = {
        "changed": changed,
        "changedTables": changed_tables,
        "previousFingerprint": previous.get("fingerprint"),
        "currentFingerprint": current.get("fingerprint"),
    }
    print(json.dumps(result, indent=2))
    if args.command == "changed":
        path.unlink(missing_ok=True)
    return 0 if changed else 10


if __name__ == "__main__":
    raise SystemExit(main())
