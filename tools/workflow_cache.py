from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "database" / ".workflow-cache"


def file_sig(path: Path) -> dict:
    try:
        st = path.stat()
        return {"path": str(path.resolve()), "exists": True, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
    except FileNotFoundError:
        return {"path": str(path.resolve()), "exists": False}


def fingerprint(paths: list[str], args: list[str]) -> str:
    records = []
    for raw in paths:
        p = (ROOT / raw).resolve() if not os.path.isabs(raw) else Path(raw).resolve()
        records.append(file_sig(p))
        # Include SQLite sidecars because committed/active changes can be in WAL.
        if p.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            records.append(file_sig(Path(str(p) + "-wal")))
            records.append(file_sig(Path(str(p) + "-shm")))
    payload = {"args": args, "files": records}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def state_path(name: str, transient: bool = False) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    suffix = ".snapshot.json" if transient else ".json"
    return CACHE_DIR / f"{safe}{suffix}"


def read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def write_state(path: Path, fp: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"fingerprint": fp}, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lightweight input fingerprint cache for CMD workflows.")
    parser.add_argument("command", choices=("current", "mark", "snapshot", "changed"))
    parser.add_argument("name")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--arg", action="append", default=[])
    ns = parser.parse_args()

    fp = fingerprint(ns.paths, ns.arg)
    if ns.command == "current":
        old = read_state(state_path(ns.name)).get("fingerprint")
        return 10 if old == fp else 0
    if ns.command == "mark":
        write_state(state_path(ns.name), fp)
        return 0
    if ns.command == "snapshot":
        write_state(state_path(ns.name, transient=True), fp)
        return 0
    if ns.command == "changed":
        snap = state_path(ns.name, transient=True)
        old = read_state(snap).get("fingerprint")
        try:
            snap.unlink()
        except FileNotFoundError:
            pass
        return 10 if old == fp else 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
