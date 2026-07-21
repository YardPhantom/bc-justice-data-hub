#!/usr/bin/env python3
"""Backfill historical BC judgment metadata and searchable text.

Sources:
- bounded discovery from configured official court/archive index pages;
- controlled CSV manifests and local HTML/PDF files;
- optional CanLII API metadata when CANLII_API_KEY is configured.

The collector never treats a discovered decision as a conviction. Every new
record remains review-required until its outcome, people, offences and sentence
are verified through the normal review workflow.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request
from secure_http import verified_urlopen

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "database" / "bc_justice.db"
DATA = ROOT / "data"
IMPORT_ROOT = ROOT / "imports" / "historical-judgments"
ARCHIVE = IMPORT_ROOT / "archive"
UA = "BCJusticeDataHub/0.6 (+private local research)"

DEFAULT_START_YEAR = 1990
COURT_CODES = {"bcpc": "BCPC", "bcsc": "BCSC", "bcca": "BCCA", "bctc": "BCTC"}
OFFICIAL_SEEDS = [
    ("BCPC", "https://provincialcourt.bc.ca/finding-judgments/recent-judgments"),
    ("BCSC", "https://www.bccourts.ca/supreme_court/recent_Judgments.aspx"),
    ("BCCA", "https://www.bccourts.ca/court_of_appeal/recent_Judgments.aspx"),
]
NON_DECISION_TITLES = {
    "home", "search", "contact", "contact us", "accessibility", "canlii",
    "finding judgments", "recent judgments", "judgments", "decisions",
    "types of judgments", "canlii guides", "skip to main content",
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_collection_runs(
 run_id TEXT PRIMARY KEY, started_at TEXT, completed_at TEXT, start_year INTEGER,
 end_year INTEGER, discovered_count INTEGER DEFAULT 0, imported_count INTEGER DEFAULT 0,
 skipped_count INTEGER DEFAULT 0, error_count INTEGER DEFAULT 0, notes TEXT
);
CREATE TABLE IF NOT EXISTS historical_judgment_sources(
 source_id TEXT PRIMARY KEY, source_type TEXT, court_level TEXT, index_url TEXT,
 local_path TEXT, enabled INTEGER DEFAULT 1, last_checked_at TEXT, last_status TEXT,
 UNIQUE(source_type, index_url, local_path)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def uid(*parts: object) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join(map(str, parts))))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_space(value: object) -> str:
    return " ".join(str(value or "").split())


def request(url: str, accept: str = "text/html,application/json,application/pdf,*/*") -> tuple[bytes, str]:
    req = Request(url, headers={"User-Agent": UA, "Accept": accept})
    with verified_urlopen(req, timeout=60) as response:
        return response.read(), response.headers.get_content_type()


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(published_judgments)")}
    additions = {
        "historical_record": "INTEGER DEFAULT 0",
        "source_category": "TEXT",
        "decision_text": "TEXT",
        "content_sha256": "TEXT",
        "collection_year": "INTEGER",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE published_judgments ADD COLUMN {name} {definition}")
    connection.commit()


def ensure_review(connection: sqlite3.Connection, judgment_id: str) -> None:
    review_id = uid("published_judgment", judgment_id, "Verify judgment outcome, sentence and publication restrictions")
    connection.execute(
        """INSERT OR IGNORE INTO review_queue(
        review_id,entity_type,entity_id,reason,severity,source_document_id,status,created_at)
        VALUES(?,?,?,'Verify judgment outcome, sentence and publication restrictions','high',NULL,'open',?)""",
        (review_id, "published_judgment", judgment_id, now()),
    )


def parse_citation(text: str) -> tuple[str, str, int | None]:
    match = re.search(r"\b((?:19|20)\d{2})\s+(BCPC|BCSC|BCCA|BCTC)\s+(\d+)\b", text, re.I)
    if not match:
        return "", "", None
    citation = f"{match.group(1)} {match.group(2).upper()} {match.group(3)}"
    return citation, match.group(2).upper(), int(match.group(1))


def year_from_text(*values: object) -> int | None:
    for value in values:
        match = re.search(r"\b((?:19|20)\d{2})\b", str(value or ""))
        if match:
            return int(match.group(1))
    return None


def title_is_decision(title: str, url: str, citation: str = "") -> bool:
    clean = normalize_space(title).casefold()
    lower_url = url.casefold()
    if not clean or clean in NON_DECISION_TITLES:
        return False
    if citation:
        return True
    if any(marker in lower_url for marker in ("/doc/", ".pdf", "/judgment", "/decision")):
        return bool(re.search(r"\bv\.?\b|\bre\b|\br\.\s*v\.|\bapplication\b", clean, re.I))
    return False


def extract_document(raw: bytes, content_type: str, url: str) -> tuple[str, str]:
    is_pdf = "pdf" in content_type or url.lower().endswith(".pdf") or raw[:4] == b"%PDF"
    if is_pdf:
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(raw))
            return "\n".join(page.extract_text() or "" for page in reader.pages), "PDF"
        except Exception as exc:
            return f"[PDF text extraction failed: {exc}]", "PDF"
    text = raw.decode("utf-8", "replace")
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, "html.parser")
        for element in soup(["script", "style", "nav", "footer"]):
            element.decompose()
        return normalize_space(soup.get_text(" ", strip=True)), "HTML"
    except Exception:
        return normalize_space(re.sub(r"<[^>]+>", " ", text)), "HTML"


def archive_document(raw: bytes, url: str, content_type: str) -> Path:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    suffix = ".pdf" if "pdf" in content_type or raw[:4] == b"%PDF" else ".html"
    path = ARCHIVE / f"{sha256(raw)[:20]}{suffix}"
    if not path.exists():
        path.write_bytes(raw)
    return path


def upsert_judgment(
    connection: sqlite3.Connection,
    *,
    court_level: str,
    title: str,
    citation: str,
    decision_date: str,
    source_url: str,
    source_index_url: str,
    source_category: str,
    document_type: str,
    decision_text: str,
    digest: str,
    collection_year: int | None,
    metadata: dict,
) -> bool:
    judgment_id = uid("judgment", source_url or citation or title)
    existed = connection.execute(
        "SELECT 1 FROM published_judgments WHERE source_url=? OR (?<>'' AND citation=?)",
        (source_url, citation, citation),
    ).fetchone()
    connection.execute(
        """INSERT INTO published_judgments(
        judgment_id,court_level,case_title,citation,decision_date,source_url,
        source_index_url,document_type,outcome_type,sentence_text,
        publication_restriction,verification_state,retrieved_at,raw_metadata,
        historical_record,source_category,decision_text,content_sha256,collection_year)
        VALUES(?,?,?,?,?,?,?,?, 'unknown','',0,'review',?,?,?,?,?,?,?)
        ON CONFLICT(source_url) DO UPDATE SET
          court_level=excluded.court_level,
          case_title=excluded.case_title,
          citation=COALESCE(NULLIF(excluded.citation,''),published_judgments.citation),
          decision_date=COALESCE(NULLIF(excluded.decision_date,''),published_judgments.decision_date),
          source_index_url=excluded.source_index_url,
          document_type=excluded.document_type,
          retrieved_at=excluded.retrieved_at,
          raw_metadata=excluded.raw_metadata,
          historical_record=1,
          source_category=excluded.source_category,
          decision_text=CASE WHEN length(excluded.decision_text)>length(COALESCE(published_judgments.decision_text,'')) THEN excluded.decision_text ELSE published_judgments.decision_text END,
          content_sha256=excluded.content_sha256,
          collection_year=excluded.collection_year""",
        (
            judgment_id, court_level, title, citation, decision_date, source_url,
            source_index_url, document_type, now(), json.dumps(metadata, ensure_ascii=False),
            1, source_category, decision_text[:2_000_000], digest, collection_year,
        ),
    )
    ensure_review(connection, judgment_id)
    return existed is None


def links_from_html(raw: bytes, base_url: str) -> list[tuple[str, str]]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, "html.parser")
    result: list[tuple[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        label = normalize_space(anchor.get_text(" ", strip=True))
        href = urljoin(base_url, anchor["href"])
        if href.startswith(("http://", "https://")):
            result.append((label, href))
    return result


def discover_official(
    connection: sqlite3.Connection,
    seeds: list[tuple[str, str]],
    start_year: int,
    end_year: int,
    max_pages: int,
    max_depth: int,
) -> tuple[int, int, int]:
    imported = skipped = errors = 0
    for default_level, seed in seeds:
        host = urlparse(seed).netloc.casefold()
        queue = deque([(seed, 0)])
        visited: set[str] = set()
        while queue and len(visited) < max_pages:
            page_url, depth = queue.popleft()
            if page_url in visited:
                continue
            visited.add(page_url)
            try:
                raw, content_type = request(page_url)
            except Exception as exc:
                errors += 1
                print(f"Historical index fetch failed: {page_url}: {exc}", file=sys.stderr)
                continue
            if "html" not in content_type:
                continue
            for title, url in links_from_html(raw, page_url):
                parsed = urlparse(url)
                if parsed.netloc.casefold() != host and "canlii.org" not in parsed.netloc.casefold():
                    continue
                citation, cited_level, cited_year = parse_citation(f"{title} {url}")
                candidate_year = cited_year or year_from_text(title, url)
                if candidate_year and not start_year <= candidate_year <= end_year:
                    continue
                if title_is_decision(title, url, citation):
                    try:
                        body, body_type = request(url)
                        decision_text, document_type = extract_document(body, body_type, url)
                        archive_path = archive_document(body, url, body_type)
                        imported += int(upsert_judgment(
                            connection,
                            court_level=cited_level or default_level,
                            title=title or citation or Path(parsed.path).stem,
                            citation=citation,
                            decision_date="",
                            source_url=url,
                            source_index_url=page_url,
                            source_category=("historical sentencing/prior-record priority" if re.search(r"\b(?:sentenc|dangerous offender|long-term offender|criminal record|prior convictions?|probation|breach)\b", f"{title} {decision_text}", re.I) else "historical official archive"),
                            document_type=document_type,
                            decision_text=decision_text,
                            digest=sha256(body),
                            collection_year=candidate_year,
                            metadata={"archivePath": str(archive_path.relative_to(ROOT)).replace("\\", "/"), "discoveredFrom": page_url},
                        ))
                    except Exception as exc:
                        errors += 1
                        print(f"Historical decision fetch failed: {url}: {exc}", file=sys.stderr)
                elif depth < max_depth:
                    lower = f"{title} {url}".casefold()
                    if any(word in lower for word in ("archive", "older", "previous", "judgment", "decision", "year")):
                        queue.append((url, depth + 1))
                else:
                    skipped += 1
            connection.commit()
    return imported, skipped, errors


def import_manifest(connection: sqlite3.Connection, manifest: Path, start_year: int, end_year: int) -> tuple[int, int, int]:
    imported = skipped = errors = 0
    if not manifest.exists():
        return imported, skipped, errors
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                source_url = normalize_space(row.get("source_url"))
                local_file = normalize_space(row.get("local_file"))
                citation = normalize_space(row.get("citation"))
                parsed_citation, cited_level, cited_year = parse_citation(citation)
                citation = citation or parsed_citation
                year = int(row["year"]) if normalize_space(row.get("year")).isdigit() else cited_year or year_from_text(row.get("decision_date"), citation, source_url, local_file)
                if year and not start_year <= year <= end_year:
                    skipped += 1
                    continue
                if local_file:
                    path = Path(local_file)
                    if not path.is_absolute():
                        path = IMPORT_ROOT / path
                    body = path.read_bytes()
                    content_type = "application/pdf" if path.suffix.lower() == ".pdf" else "text/html"
                    canonical_url = source_url or path.resolve().as_uri()
                elif source_url:
                    body, content_type = request(source_url)
                    canonical_url = source_url
                else:
                    skipped += 1
                    continue
                decision_text, document_type = extract_document(body, content_type, canonical_url)
                archive_path = archive_document(body, canonical_url, content_type)
                imported += int(upsert_judgment(
                    connection,
                    court_level=normalize_space(row.get("court_level")) or cited_level or "Other BC decision-maker",
                    title=normalize_space(row.get("case_title")) or citation or Path(urlparse(canonical_url).path).stem,
                    citation=citation,
                    decision_date=normalize_space(row.get("decision_date")),
                    source_url=canonical_url,
                    source_index_url=normalize_space(row.get("source_index_url")) or str(manifest),
                    source_category=normalize_space(row.get("source_category")) or ("historical sentencing/prior-record priority" if re.search(r"\b(?:sentenc|dangerous offender|long-term offender|criminal record|prior convictions?|probation|breach)\b", f"{title} {decision_text}", re.I) else "controlled historical import"),
                    document_type=document_type,
                    decision_text=decision_text,
                    digest=sha256(body),
                    collection_year=year,
                    metadata={"archivePath": str(archive_path.relative_to(ROOT)).replace("\\", "/"), "manifest": str(manifest.relative_to(ROOT)) if manifest.is_relative_to(ROOT) else str(manifest)},
                ))
            except Exception as exc:
                errors += 1
                print(f"Historical manifest row failed: {exc}", file=sys.stderr)
    connection.commit()
    return imported, skipped, errors


def collect_canlii_api(connection: sqlite3.Connection, start_year: int, end_year: int, limit: int) -> tuple[int, int, int]:
    api_key = os.environ.get("CANLII_API_KEY", "").strip()
    if not api_key:
        print("CANLII_API_KEY is not set; skipping optional CanLII API metadata backfill.")
        return 0, 0, 0
    imported = skipped = errors = 0
    for database_id, level in COURT_CODES.items():
        offset = 0
        while offset < limit:
            params = urlencode({"api_key": api_key, "offset": offset, "resultCount": min(100, limit - offset)})
            url = f"https://api.canlii.org/v1/caseBrowse/en/{database_id}/?{params}"
            try:
                raw, _ = request(url, "application/json")
                payload = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                errors += 1
                print(f"CanLII API failed for {database_id}: {exc}", file=sys.stderr)
                break
            cases = payload.get("cases") or payload.get("caseBrowse") or []
            if not cases:
                break
            for item in cases:
                citation = normalize_space(item.get("citation"))
                year = year_from_text(item.get("decisionDate"), citation)
                if year and not start_year <= year <= end_year:
                    skipped += 1
                    continue
                case_id = item.get("caseId") or item.get("caseIdEn") or ""
                source_url = item.get("url") or (f"https://www.canlii.org/en/bc/{database_id}/doc/{year or ''}/{case_id}/{case_id}.html" if case_id else "")
                if not source_url:
                    skipped += 1
                    continue
                title = normalize_space(item.get("title")) or citation
                imported += int(upsert_judgment(
                    connection,
                    court_level=level,
                    title=title,
                    citation=citation,
                    decision_date=normalize_space(item.get("decisionDate")),
                    source_url=source_url,
                    source_index_url=url,
                    source_category="CanLII API metadata",
                    document_type="HTML",
                    decision_text="",
                    digest=sha256(json.dumps(item, sort_keys=True).encode()),
                    collection_year=year,
                    metadata={"canlii": item, "metadataOnly": True},
                ))
            connection.commit()
            offset += len(cases)
            if len(cases) < min(100, limit - offset + len(cases)):
                break
    return imported, skipped, errors


def export(connection: sqlite3.Connection) -> None:
    DATA.mkdir(exist_ok=True)
    rows = [dict(row) for row in connection.execute(
        """SELECT judgment_id,court_level,case_title,citation,decision_date,source_url,
        source_index_url,document_type,outcome_type,sentence_text,publication_restriction,
        verification_state,retrieved_at,historical_record,source_category,collection_year
        FROM published_judgments WHERE historical_record=1
        ORDER BY COALESCE(decision_date,printf('%04d',collection_year),retrieved_at) DESC"""
    )]
    summary: dict[str, int] = {}
    for row in rows:
        key = str(row.get("court_level") or "Other")
        summary[key] = summary.get(key, 0) + 1
    payload = {
        "generatedAt": now(),
        "notice": "Historical decisions remain review-required until identity, offence and outcome fields are verified.",
        "total": len(rows),
        "byCourt": summary,
        "judgments": rows,
    }
    (DATA / "historical-judgments.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def execute_with_retry(connection: sqlite3.Connection, sql: str, params: tuple = (), attempts: int = 8):
    for attempt in range(attempts):
        try:
            return connection.execute(sql, params)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == attempts - 1:
                raise
            time.sleep(min(0.5 * (attempt + 1), 3.0))

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int, default=datetime.now().year)
    parser.add_argument("--manifest", type=Path, default=IMPORT_ROOT / "historical-judgments.csv")
    parser.add_argument("--official", action="store_true", help="Discover bounded official archive/index pages")
    parser.add_argument("--canlii-api", action="store_true", help="Use optional CanLII API metadata when CANLII_API_KEY is set")
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--canlii-limit", type=int, default=1000)
    parser.add_argument("--export-only", action="store_true")
    args = parser.parse_args(argv)
    if args.start_year > args.end_year:
        parser.error("start year must not exceed end year")
    DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB, timeout=60)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA busy_timeout=60000')
    try:
        connection.execute('PRAGMA journal_mode=WAL')
    except sqlite3.OperationalError:
        pass
    ensure_schema(connection)
    if args.export_only:
        export(connection)
        connection.close()
        return 0
    run_id = uid("historical-run", now(), args.start_year, args.end_year)
    execute_with_retry(
        connection,
        "INSERT INTO historical_collection_runs(run_id,started_at,start_year,end_year,notes) VALUES(?,?,?,?,?)",
        (run_id, now(), args.start_year, args.end_year, "review-required historical backfill"),
    )
    connection.commit()
    imported = skipped = errors = 0
    a, b, c = import_manifest(connection, args.manifest, args.start_year, args.end_year)
    imported += a; skipped += b; errors += c
    if args.official:
        a, b, c = discover_official(connection, OFFICIAL_SEEDS, args.start_year, args.end_year, args.max_pages, args.max_depth)
        imported += a; skipped += b; errors += c
    if args.canlii_api:
        a, b, c = collect_canlii_api(connection, args.start_year, args.end_year, args.canlii_limit)
        imported += a; skipped += b; errors += c
    export(connection)
    execute_with_retry(
        connection,
        """UPDATE historical_collection_runs SET completed_at=?,discovered_count=?,imported_count=?,skipped_count=?,error_count=? WHERE run_id=?""",
        (now(), imported + skipped, imported, skipped, errors, run_id),
    )
    connection.commit()
    print(json.dumps({"imported": imported, "skipped": skipped, "errors": errors, "startYear": args.start_year, "endYear": args.end_year}, indent=2))
    connection.close()
    return 1 if errors and not imported else 0


if __name__ == "__main__":
    raise SystemExit(main())
