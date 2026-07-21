#!/usr/bin/env python3
"""Sync BC Data Catalogue metadata and optionally download supported resources."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "data" / "catalogue-config.json"
DB_PATH = ROOT / "database" / "bc_justice.db"
EXPORT_PATH = ROOT / "data" / "catalogue-datasets.json"
DOWNLOAD_DIR = ROOT / "imports" / "catalogue"
REPORT_DIR = ROOT / "reports"
LOG_PATH = REPORT_DIR / "sync-catalogue-latest.log"
UA = "BC-Justice-Data-Hub/0.8.4 (+private local research)"
HEARTBEAT_SECONDS = 15
DOWNLOAD_CHUNK = 1024 * 1024
MAX_RETRIES = 3

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS catalogue_datasets (
  dataset_id TEXT PRIMARY KEY, name TEXT, title TEXT NOT NULL, notes TEXT,
  organization TEXT, owner_org TEXT, metadata_created TEXT, metadata_modified TEXT,
  update_frequency TEXT, license_id TEXT, license_title TEXT, catalogue_url TEXT,
  matched_terms TEXT, active INTEGER DEFAULT 1, first_seen TEXT, last_seen TEXT,
  raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS catalogue_resources (
  resource_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, name TEXT, description TEXT,
  format TEXT, media_type TEXT, url TEXT, resource_type TEXT, created TEXT,
  last_modified TEXT, size INTEGER, hash TEXT, datastore_active INTEGER DEFAULT 0,
  local_path TEXT, downloaded_at TEXT, download_sha256 TEXT, last_seen TEXT,
  raw_json TEXT NOT NULL,
  FOREIGN KEY(dataset_id) REFERENCES catalogue_datasets(dataset_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS catalogue_sync_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
  status TEXT NOT NULL, query_count INTEGER DEFAULT 0, dataset_count INTEGER DEFAULT 0,
  resource_count INTEGER DEFAULT 0, downloaded_count INTEGER DEFAULT 0, error_text TEXT
);
CREATE INDEX IF NOT EXISTS idx_catalogue_title ON catalogue_datasets(title);
CREATE INDEX IF NOT EXISTS idx_resource_dataset ON catalogue_resources(dataset_id);
CREATE INDEX IF NOT EXISTS idx_resource_format ON catalogue_resources(format);
"""


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def elapsed(start):
    seconds = max(0, int(time.monotonic() - start))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def human_bytes(value):
    if value is None:
        return "unknown size"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024


def bar(percent, width=20):
    percent = max(0, min(100, int(percent)))
    filled = round(width * percent / 100)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


class Reporter:
    def __init__(self, verbose=False):
        self.verbose = verbose
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        self.log = LOG_PATH.open("w", encoding="utf-8")

    def close(self):
        self.log.close()

    def write(self, message, *, detail=False, error=False):
        timestamped = f"{now()} {message}"
        self.log.write(timestamped + "\n")
        self.log.flush()
        if not detail or self.verbose:
            print(message, file=sys.stderr if error else sys.stdout, flush=True)


def request_with_heartbeat(url, reporter, *, label, timeout, accept_json=False):
    result = {}
    failure = {}
    done = threading.Event()

    def worker():
        try:
            headers = {"User-Agent": UA}
            if accept_json:
                headers["Accept"] = "application/json"
            request = Request(url, headers=headers)
            result["response"] = urlopen(request, timeout=timeout)
        except Exception as exc:  # re-raised below
            failure["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    started = time.monotonic()
    while not done.wait(HEARTBEAT_SECONDS):
        reporter.write(f"Still waiting for {label}... {elapsed(started)}")
    if "error" in failure:
        raise failure["error"]
    return result["response"]


def api_get(url, reporter, label):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if attempt > 1:
                reporter.write(f"{label}: retry {attempt}/{MAX_RETRIES}...")
            with request_with_heartbeat(url, reporter, label=label, timeout=60, accept_json=True) as response:
                payload = json.load(response)
            if not payload.get("success"):
                raise RuntimeError(f"Catalogue API returned success=false: {url}")
            return payload["result"]
        except (HTTPError, URLError, TimeoutError, RuntimeError, ValueError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                delay = attempt * 5
                reporter.write(f"{label}: request failed ({exc}); retrying in {delay}s.", error=True)
                time.sleep(delay)
    raise RuntimeError(f"{label}: failed after {MAX_RETRIES} attempts: {last_error}")


def safe_filename(resource):
    name = resource.get("name") or Path(urlparse(resource.get("url", "")).path).name or resource["id"]
    name = "".join(c if c.isalnum() or c in "._- " else "_" for c in name).strip().replace(" ", "-")
    if "." not in Path(name).name and resource.get("format"):
        name += "." + str(resource.get("format") or "dat").lower()
    return f"{resource['id']}-{name}"[:220]


def download_resource(resource, delay, reporter, resource_label):
    url = resource.get("url")
    if not url or not url.lower().startswith(("http://", "https://")):
        reporter.write(f"{resource_label}: skipped because the resource URL is missing or unsupported.")
        return None
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = DOWNLOAD_DIR / safe_filename(resource)
    partial = path.with_suffix(path.suffix + ".part")
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if attempt > 1:
                reporter.write(f"{resource_label}: retry {attempt}/{MAX_RETRIES}...")
            reporter.write(f"{resource_label}: connecting to {urlparse(url).netloc}...")
            response = request_with_heartbeat(url, reporter, label=resource_label, timeout=120)
            with response:
                length_header = response.headers.get("Content-Length")
                total = int(length_header) if length_header and length_header.isdigit() else None
                reporter.write(f"{resource_label}: downloading {human_bytes(total)}...")
                h = hashlib.sha256()
                downloaded = 0
                last_percent = -5
                last_unknown_report = 0
                with partial.open("wb") as out:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        h.update(chunk)
                        downloaded += len(chunk)
                        if total:
                            percent = min(100, int(downloaded * 100 / total))
                            bucket = (percent // 5) * 5
                            if bucket >= last_percent + 5 or percent == 100:
                                reporter.write(
                                    f"{resource_label}: {bar(percent)} {percent}% | "
                                    f"{human_bytes(downloaded)} / {human_bytes(total)}"
                                )
                                last_percent = bucket
                        elif downloaded - last_unknown_report >= 10 * DOWNLOAD_CHUNK:
                            reporter.write(f"{resource_label}: {human_bytes(downloaded)} downloaded")
                            last_unknown_report = downloaded
                partial.replace(path)
                reporter.write(f"{resource_label}: download complete ({human_bytes(downloaded)}).")
                time.sleep(delay)
                return str(path.relative_to(ROOT)).replace("\\", "/"), h.hexdigest()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            if attempt < MAX_RETRIES:
                wait = attempt * 5
                reporter.write(f"{resource_label}: download failed ({exc}); retrying in {wait}s.", error=True)
                time.sleep(wait)
    raise RuntimeError(f"{resource_label}: download failed after {MAX_RETRIES} attempts: {last_error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true", help="Download configured CSV/XLS/XLSX/JSON/PDF resources")
    parser.add_argument("--term", action="append", help="Override configured search terms; repeatable")
    parser.add_argument("--limit", type=int, default=0, help="Maximum unique datasets for a test run")
    parser.add_argument("--import", dest="import_after", action="store_true", help="Import downloaded files and refresh the local data explorer")
    parser.add_argument("--incremental", action="store_true", help="Download only new or changed resources")
    parser.add_argument("--verbose", action="store_true", help="Show URLs and detailed skip information")
    parser.add_argument("--force", action="store_true", help="Redownload supported resources even when metadata is unchanged")
    parser.add_argument("--quick", action="store_true", help="Check metadata and skip downstream import/export when no resources changed")
    args = parser.parse_args()

    reporter = Reporter(args.verbose)
    run_started = time.monotonic()
    conn = None
    run_id = None
    counters = {"resources": 0, "downloaded": 0, "unchanged": 0, "failed": 0, "skipped": 0}
    try:
        reporter.write("[1/6] Preparing local database and catalogue configuration...")
        subprocess.run([sys.executable, "-u", str(ROOT / "tools" / "data_pipeline.py"), "setup"], check=True)
        cfg = load_config()
        terms = args.term or cfg["search_terms"]
        conn = sqlite3.connect(DB_PATH)
        conn.executescript(SCHEMA)
        started = now()
        cur = conn.execute(
            "INSERT INTO catalogue_sync_runs(started_at,status,query_count) VALUES(?,?,?)",
            (started, "running", len(terms)),
        )
        run_id = cur.lastrowid
        conn.commit()

        reporter.write(f"[2/6] Searching BC Data Catalogue with {len(terms)} search terms...")
        found = {}
        term_hits = {}
        for index, term in enumerate(terms, 1):
            reporter.write(f"Search term {index}/{len(terms)}: {term}")
            params = urlencode({"q": term, "rows": cfg.get("rows_per_query", 100), "start": 0})
            result = api_get(f"{cfg['api_base']}/package_search?{params}", reporter, f"Catalogue search '{term}'")
            before = len(found)
            for ds in result.get("results", []):
                found[ds["id"]] = ds
                term_hits.setdefault(ds["id"], set()).add(term)
                if args.limit and len(found) >= args.limit:
                    break
            reporter.write(f"Search term {index}/{len(terms)} complete: {len(found)-before} new datasets; {len(found)} unique total.")
            time.sleep(cfg.get("request_delay_seconds", 0.35))
            if args.limit and len(found) >= args.limit:
                break

        reporter.write(f"[3/6] Processing {len(found)} datasets and their resources...")
        seen = now()
        download_formats = set(cfg.get("download_formats", []))
        for dataset_index, (ds_id, ds) in enumerate(found.items(), 1):
            dataset_started = time.monotonic()
            title = ds.get("title") or ds_id
            resources = ds.get("resources", [])
            reporter.write(f"Dataset {dataset_index}/{len(found)}: {title} ({len(resources)} resources)")
            catalogue_url = cfg.get("catalogue_base", "https://catalogue.data.gov.bc.ca/dataset/") + (ds.get("name") or ds_id)
            org = ds.get("organization") or {}
            conn.execute(
                """INSERT INTO catalogue_datasets (
                  dataset_id,name,title,notes,organization,owner_org,metadata_created,metadata_modified,update_frequency,
                  license_id,license_title,catalogue_url,matched_terms,active,first_seen,last_seen,raw_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(dataset_id) DO UPDATE SET name=excluded.name,title=excluded.title,notes=excluded.notes,
                  organization=excluded.organization,owner_org=excluded.owner_org,metadata_created=excluded.metadata_created,
                  metadata_modified=excluded.metadata_modified,update_frequency=excluded.update_frequency,
                  license_id=excluded.license_id,license_title=excluded.license_title,catalogue_url=excluded.catalogue_url,
                  matched_terms=excluded.matched_terms,active=1,last_seen=excluded.last_seen,raw_json=excluded.raw_json""",
                (
                    ds_id, ds.get("name"), title, ds.get("notes"), org.get("title") or org.get("name"), ds.get("owner_org"),
                    ds.get("metadata_created"), ds.get("metadata_modified"), ds.get("update_frequency"), ds.get("license_id"),
                    ds.get("license_title"), catalogue_url, json.dumps(sorted(term_hits[ds_id])), 1, seen, seen,
                    json.dumps(ds, ensure_ascii=False),
                ),
            )
            for resource_index, r in enumerate(resources, 1):
                counters["resources"] += 1
                fmt = (r.get("format") or "").upper()
                resource_name = r.get("name") or r.get("id") or "unnamed resource"
                resource_label = f"  Resource {resource_index}/{len(resources)}: {resource_name}"
                reporter.write(f"{resource_label} [{fmt or 'unknown format'}]")
                reporter.write(f"{resource_label} URL: {r.get('url') or 'none'}", detail=True)
                local_path = sha = downloaded_at = None
                existing = conn.execute(
                    "SELECT url,last_modified,size,hash,local_path,download_sha256 FROM catalogue_resources WHERE resource_id=?",
                    (r["id"],),
                ).fetchone()
                unchanged = False
                if args.incremental and not args.force and existing and existing[4]:
                    existing_path = ROOT / existing[4]
                    same_url = (existing[0] or "") == (r.get("url") or "")
                    same_modified = bool(r.get("last_modified") and existing[1] == r.get("last_modified"))
                    same_hash = bool(r.get("hash") and existing[3] == r.get("hash"))
                    same_size = r.get("size") is not None and existing[2] == r.get("size")
                    unchanged = existing_path.exists() and same_url and (same_modified or same_hash or same_size)
                    if unchanged:
                        local_path, sha = existing[4], existing[5]
                        counters["unchanged"] += 1
                        reporter.write(f"{resource_label}: unchanged; existing local file retained.")
                if args.download and fmt in download_formats and not unchanged:
                    try:
                        result = download_resource(r, cfg.get("request_delay_seconds", 0.35), reporter, resource_label)
                        if result:
                            local_path, sha = result
                            downloaded_at = now()
                            counters["downloaded"] += 1
                    except Exception as exc:
                        counters["failed"] += 1
                        reporter.write(f"{resource_label}: failed: {exc}", error=True)
                elif args.download and fmt not in download_formats:
                    counters["skipped"] += 1
                    reporter.write(f"{resource_label}: skipped unsupported format {fmt or 'unknown'}.", detail=True)
                conn.execute(
                    """INSERT INTO catalogue_resources (
                      resource_id,dataset_id,name,description,format,media_type,url,resource_type,created,last_modified,
                      size,hash,datastore_active,local_path,downloaded_at,download_sha256,last_seen,raw_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                      ON CONFLICT(resource_id) DO UPDATE SET dataset_id=excluded.dataset_id,name=excluded.name,description=excluded.description,
                      format=excluded.format,media_type=excluded.media_type,url=excluded.url,resource_type=excluded.resource_type,
                      created=excluded.created,last_modified=excluded.last_modified,size=excluded.size,hash=excluded.hash,
                      datastore_active=excluded.datastore_active,local_path=COALESCE(excluded.local_path,catalogue_resources.local_path),
                      downloaded_at=COALESCE(excluded.downloaded_at,catalogue_resources.downloaded_at),
                      download_sha256=COALESCE(excluded.download_sha256,catalogue_resources.download_sha256),last_seen=excluded.last_seen,raw_json=excluded.raw_json""",
                    (
                        r["id"], ds_id, r.get("name"), r.get("description"), fmt, r.get("mimetype"), r.get("url"),
                        r.get("resource_type"), r.get("created"), r.get("last_modified"), r.get("size"), r.get("hash"),
                        int(bool(r.get("datastore_active"))), local_path, downloaded_at, sha, seen,
                        json.dumps(r, ensure_ascii=False),
                    ),
                )
            conn.commit()
            reporter.write(
                f"Dataset {dataset_index}/{len(found)} complete in {elapsed(dataset_started)} | "
                f"resources {counters['resources']} | downloaded {counters['downloaded']} | "
                f"unchanged {counters['unchanged']} | failed {counters['failed']}"
            )

        reporter.write("[4/6] Finalizing catalogue database records...")
        conn.execute(
            "UPDATE catalogue_sync_runs SET finished_at=?,status='complete',dataset_count=?,resource_count=?,downloaded_count=? WHERE run_id=?",
            (now(), len(found), counters["resources"], counters["downloaded"], run_id),
        )
        conn.commit()

        reporter.write("[5/6] Writing website catalogue export...")
        export_rows = []
        for row in conn.execute(
            """SELECT d.dataset_id,d.title,d.notes,d.organization,d.metadata_modified,d.update_frequency,d.license_title,
              d.catalogue_url,d.matched_terms,COUNT(r.resource_id),GROUP_CONCAT(DISTINCT r.format)
              FROM catalogue_datasets d LEFT JOIN catalogue_resources r ON r.dataset_id=d.dataset_id
              WHERE d.active=1 GROUP BY d.dataset_id ORDER BY d.metadata_modified DESC,d.title"""
        ):
            export_rows.append(
                {
                    "id": row[0], "title": row[1], "notes": row[2] or "", "organization": row[3] or "",
                    "modified": row[4] or "", "frequency": row[5] or "", "license": row[6] or "", "url": row[7],
                    "matchedTerms": json.loads(row[8] or "[]"), "resourceCount": row[9],
                    "formats": [x for x in (row[10] or "").split(",") if x],
                }
            )
        EXPORT_PATH.write_text(
            json.dumps({"generatedAt": now(), "count": len(export_rows), "datasets": export_rows}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        command = "all" if args.import_after else "export"
        if args.quick and counters["downloaded"] == 0:
            reporter.write("[6/6] No catalogue resources changed; skipping downstream pipeline refresh.")
        else:
            reporter.write(f"[6/6] Running data pipeline '{command}' refresh...")
            subprocess.run([sys.executable, "-u", str(ROOT / "tools" / "data_pipeline.py"), command], check=True)
        reporter.write(
            "Catalogue sync complete | "
            f"datasets {len(found)} | resources {counters['resources']} | downloaded {counters['downloaded']} | "
            f"unchanged {counters['unchanged']} | skipped {counters['skipped']} | failed {counters['failed']} | "
            f"elapsed {elapsed(run_started)}"
        )
        reporter.write(f"Detailed log: {LOG_PATH.relative_to(ROOT)}")
        return 0
    except Exception as exc:
        if conn is not None and run_id is not None:
            conn.execute(
                "UPDATE catalogue_sync_runs SET finished_at=?,status='failed',error_text=? WHERE run_id=?",
                (now(), str(exc), run_id),
            )
            conn.commit()
        reporter.write(f"Sync failed: {exc}", error=True)
        reporter.write(f"Detailed log: {LOG_PATH.relative_to(ROOT)}")
        return 1
    finally:
        if conn is not None:
            conn.close()
        reporter.close()


if __name__ == "__main__":
    raise SystemExit(main())
