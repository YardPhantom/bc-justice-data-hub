#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
DATABASE = ROOT / "database"
LOCK = DATABASE / "identity-postprocess.lock"
STATUS = DATA / "post-processing-status.json"
LATEST_LOG = REPORTS / "identity-postprocess-latest.log"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def active_lock() -> dict | None:
    try:
        payload = json.loads(LOCK.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        payload = None
    if payload and process_running(int(payload.get("pid") or 0)):
        return payload
    LOCK.unlink(missing_ok=True)
    return None


def acquire_lock(identity_changed: bool) -> None:
    DATABASE.mkdir(parents=True, exist_ok=True)
    existing = active_lock()
    if existing:
        raise RuntimeError(
            f"Identity post-processing is already running as PID {existing.get('pid')}."
        )
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(LOCK, flags)
    except FileExistsError:
        existing = active_lock()
        if existing:
            raise RuntimeError(
                f"Identity post-processing is already running as PID {existing.get('pid')}."
            )
        fd = os.open(LOCK, flags)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "pid": os.getpid(),
                "startedAt": now(),
                "identityChanged": identity_changed,
            },
            handle,
            indent=2,
        )


def run_step(label: str, args: list[str], log_handle) -> None:
    line = f"\n[{now()}] {label}\n"
    print(line.strip(), flush=True)
    log_handle.write(line)
    log_handle.flush()
    process = subprocess.Popen(
        args,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    for output in process.stdout:
        print(output, end="", flush=True)
        log_handle.write(output)
    process.wait()
    log_handle.flush()
    if process.returncode:
        raise RuntimeError(f"{label} failed with exit code {process.returncode}.")


def set_status(status: str, message: str, **extra) -> None:
    payload = {
        "generatedAt": now(),
        "status": status,
        "message": message,
        "pid": os.getpid(),
        "log": str(LATEST_LOG.relative_to(ROOT)),
        **extra,
    }
    write_json_atomic(STATUS, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Collect New post-processing safely.")
    parser.add_argument("--identity-changed", action="store_true")
    parser.add_argument("--check", action="store_true", help="Return 20 when post-processing is active.")
    args = parser.parse_args()

    if args.check:
        lock = active_lock()
        if lock:
            print(json.dumps({"active": True, **lock}, indent=2))
            return 20
        print(json.dumps({"active": False}))
        return 0

    REPORTS.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    started = now()
    try:
        acquire_lock(args.identity_changed)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 20

    mode_text = "identity and advanced" if args.identity_changed else "non-identity advanced"
    set_status(
        "running",
        f"Collection is complete. {mode_text.capitalize()} post-processing is running.",
        startedAt=started,
        identityChanged=args.identity_changed,
        phase="starting",
    )
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "collection_summary.py"), "postprocessing", "0"],
        cwd=ROOT,
        check=False,
    )

    try:
        with LATEST_LOG.open("w", encoding="utf-8") as log:
            log.write(f"BC Justice Data Hub post-processing\nStarted: {started}\n")
            if args.identity_changed:
                set_status(
                    "running",
                    "Collection is complete. Building person identities.",
                    startedAt=started,
                    identityChanged=True,
                    phase="person-identities",
                )
                run_step(
                    "Building person identities",
                    [sys.executable, str(ROOT / "tools" / "person_identity.py")],
                    log,
                )
                advanced_profile = "all"
            else:
                advanced_profile = "nonidentity"

            set_status(
                "running",
                "Collection is complete. Building advanced features and refreshed indexes.",
                startedAt=started,
                identityChanged=args.identity_changed,
                phase="advanced-features",
            )
            run_step(
                "Building advanced features",
                [
                    sys.executable,
                    "-u",
                    str(ROOT / "tools" / "advanced_features.py"),
                    "--profile",
                    advanced_profile,
                ],
                log,
            )

            set_status(
                "running",
                "Collection is complete. Refreshing final dashboard snapshots.",
                startedAt=started,
                identityChanged=args.identity_changed,
                phase="final-export",
            )
            run_step(
                "Refreshing final dashboard snapshots",
                [sys.executable, str(ROOT / "tools" / "data_pipeline.py"), "export"],
                log,
            )
            if args.identity_changed:
                run_step(
                    "Marking identity workflow current",
                    [
                        sys.executable,
                        str(ROOT / "tools" / "workflow_cache.py"),
                        "mark",
                        "person-identity",
                        "database/bc_justice.db",
                        "tools/person_identity.py",
                        "tools/advanced_features.py",
                    ],
                    log,
                )
            run_step(
                "Updating collection summary",
                [sys.executable, str(ROOT / "tools" / "collection_summary.py"), "success", "0"],
                log,
            )
            run_step(
                "Updating collection alerts",
                [sys.executable, str(ROOT / "tools" / "collection_alerts.py"), "success"],
                log,
            )

        completed = now()
        set_status(
            "complete",
            "All processing is complete.",
            startedAt=started,
            completedAt=completed,
            identityChanged=args.identity_changed,
            phase="complete",
            exitCode=0,
        )
        print("All processing is complete.")
        return 0
    except Exception as exc:
        completed = now()
        set_status(
            "failed",
            f"Post-processing failed: {exc}",
            startedAt=started,
            completedAt=completed,
            identityChanged=args.identity_changed,
            phase="failed",
            exitCode=1,
        )
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / "collection_summary.py"), "postprocess-failed", "1"],
            cwd=ROOT,
            check=False,
        )
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / "collection_alerts.py"), "postprocess-failed"],
            cwd=ROOT,
            check=False,
        )
        print(f"Post-processing failed: {exc}", file=sys.stderr)
        return 1
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
