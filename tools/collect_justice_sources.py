#!/usr/bin/env python3
"""Collect BC daily court lists, published judgment indexes, and CSO case imports.

Conservative rules:
- appearances are scheduled appearances only, never guilt findings
- published judgments remain review-required until verified
- CSO data comes from controlled local CSV imports
- corrected daily court files preserve prior versions instead of overwriting them
"""
from __future__ import annotations
import argparse, csv, hashlib, json, re, sqlite3, sys, unicodedata, uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request

from secure_http import verified_urlopen
from export_utils import write_json_atomic, write_paged_records

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'database' / 'bc_justice.db'
DATA = ROOT / 'data'
IMPORTS = ROOT / 'imports'
ARCHIVE = IMPORTS / 'justice-sources'
UA = 'BCJusticeDataHub/0.8.4 (+private local research)'

DAILY_PAGE = 'https://www2.gov.bc.ca/gov/content/justice/courthouse-services/daily-court-lists/criminal-court-lists'
DAILY_INDEXES = [
    ('Provincial Court', 'https://justice.gov.bc.ca/courts/DAPCindex.html'),
    ('Provincial Court Advance', 'https://justice.gov.bc.ca/courts/PCDCindex.html'),
    ('Supreme Court', 'https://justice.gov.bc.ca/courts/DASCindex.html'),
    ('Supreme Court Completed', 'https://justice.gov.bc.ca/courts/SCDCindex.html'),
]
CSO_HOME = 'https://justice.gov.bc.ca/cso/esearch/esearchHome.do'

NON_JUDGMENT_TITLES = {
    'skip to main content', 'finding judgments', 'types of judgments', 'bail hearing results',
    'judgments', 'canlii', 'canlii guides', 'home', 'search', 'contact us', 'accessibility'
}
NON_JUDGMENT_PHRASES = (
    'different ways that provincial court judgments may be delivered',
    'bc provincial court judgments are found on canlii',
    'canlii primer, how to search, how to filter',
)
JUDGMENT_SOURCES = [
    ('BCPC', 'https://provincialcourt.bc.ca/finding-judgments/recent-judgments'),
    ('BCSC', 'https://www.bccourts.ca/supreme_court/recent_Judgments.aspx'),
    ('BCCA', 'https://www.bccourts.ca/court_of_appeal/recent_Judgments.aspx'),
]

SCHEMA = '''
CREATE TABLE IF NOT EXISTS daily_court_documents(
 document_id TEXT PRIMARY KEY, court_level TEXT, list_date TEXT, title TEXT,
 source_url TEXT UNIQUE, local_path TEXT, sha256 TEXT, retrieved_at TEXT,
 parse_status TEXT, raw_text TEXT, page_count INTEGER DEFAULT 0,
 document_key TEXT, current_version_id TEXT, first_seen_at TEXT, last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS daily_court_document_versions(
 version_id TEXT PRIMARY KEY, document_key TEXT NOT NULL, source_url TEXT NOT NULL,
 court_level TEXT, list_date TEXT, title TEXT, local_path TEXT, sha256 TEXT,
 retrieved_at TEXT, parse_status TEXT, raw_text TEXT, page_count INTEGER DEFAULT 0,
 is_current INTEGER DEFAULT 1, superseded_at TEXT,
 UNIQUE(document_key, sha256)
);
CREATE TABLE IF NOT EXISTS daily_appearances(
 appearance_id TEXT PRIMARY KEY, document_id TEXT, list_date TEXT, court_level TEXT,
 courthouse_name TEXT, courthouse_slug TEXT, courtroom TEXT, appearance_time TEXT,
 participant_name TEXT, court_file_number TEXT, appearance_type TEXT,
 legal_status TEXT DEFAULT 'scheduled_appearance', allegation_notice TEXT,
 source_url TEXT, verification_state TEXT DEFAULT 'review', raw_line TEXT,
 document_key TEXT, document_version_id TEXT, appearance_key TEXT,
 is_current INTEGER DEFAULT 1, superseded_at TEXT, superseded_by_appearance_id TEXT,
 FOREIGN KEY(document_id) REFERENCES daily_court_documents(document_id)
);
CREATE TABLE IF NOT EXISTS published_judgments(
 judgment_id TEXT PRIMARY KEY, court_level TEXT, case_title TEXT, citation TEXT,
 decision_date TEXT, judge TEXT, courthouse_name TEXT, courthouse_slug TEXT,
 source_url TEXT UNIQUE, source_index_url TEXT, document_type TEXT,
 outcome_type TEXT DEFAULT 'unknown', sentence_text TEXT,
 publication_restriction INTEGER DEFAULT 0, verification_state TEXT DEFAULT 'review',
 retrieved_at TEXT, raw_metadata TEXT
);
CREATE TABLE IF NOT EXISTS cso_import_batches(
 batch_id TEXT PRIMARY KEY, source_file TEXT, sha256 TEXT UNIQUE, imported_at TEXT,
 row_count INTEGER DEFAULT 0, error_count INTEGER DEFAULT 0
);
'''


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def slug(value: str) -> str:
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', str(value or '').lower())).strip('-')


def normalize_space(value: str) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def normalize_appearance_name(value: str) -> str:
    text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii').casefold()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


def normalize_court_file(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', str(value or '').casefold())


def refresh_appearance_search_cache(c: sqlite3.Connection, appearances: list[dict], source_stamp: str) -> None:
    c.executescript('''
    CREATE TABLE IF NOT EXISTS appearance_search_records(
     appearance_id TEXT PRIMARY KEY,
     participant_name TEXT NOT NULL DEFAULT '', normalized_name TEXT NOT NULL DEFAULT '',
     court_file_number TEXT NOT NULL DEFAULT '', normalized_court_file TEXT NOT NULL DEFAULT '',
     courthouse_name TEXT NOT NULL DEFAULT '', list_date TEXT NOT NULL DEFAULT '',
     charge_confidence TEXT NOT NULL DEFAULT 'Charge Not Available', payload_json TEXT NOT NULL,
     updated_at TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS appearance_search_meta(key TEXT PRIMARY KEY,value TEXT);
    CREATE INDEX IF NOT EXISTS idx_appearance_search_name ON appearance_search_records(normalized_name);
    CREATE INDEX IF NOT EXISTS idx_appearance_search_court ON appearance_search_records(courthouse_name);
    CREATE INDEX IF NOT EXISTS idx_appearance_search_date ON appearance_search_records(list_date);
    CREATE INDEX IF NOT EXISTS idx_appearance_search_confidence ON appearance_search_records(charge_confidence);
    CREATE INDEX IF NOT EXISTS idx_appearance_search_file ON appearance_search_records(normalized_court_file);
    ''')
    updated = now()
    rows = []
    for index, item in enumerate(appearances):
        name = normalize_space(item.get('participant_name'))
        if not name:
            continue
        appearance_id = str(item.get('appearance_id') or f"export-{index}-{normalize_court_file(item.get('court_file_number'))}-{normalize_appearance_name(name)}-{item.get('list_date', '')}")
        rows.append((
            appearance_id, name, normalize_appearance_name(name), normalize_space(item.get('court_file_number')),
            normalize_court_file(item.get('court_file_number')), normalize_space(item.get('courthouse_name')),
            normalize_space(item.get('list_date')), normalize_space(item.get('charge_confidence')) or 'Charge Not Available',
            json.dumps(item, ensure_ascii=False, separators=(',', ':')), updated,
        ))
    c.execute('DELETE FROM appearance_search_records')
    c.executemany('INSERT OR REPLACE INTO appearance_search_records VALUES(?,?,?,?,?,?,?,?,?,?)', rows)
    c.execute("INSERT OR REPLACE INTO appearance_search_meta(key,value) VALUES('source_stamp',?)", (source_stamp,))
    c.execute("INSERT OR REPLACE INTO appearance_search_meta(key,value) VALUES('updated_at',?)", (updated,))
    c.commit()


def normalize_list_date(value: str) -> str:
    text = normalize_space(value)
    if not text:
        return datetime.now().date().isoformat()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%b %d, %Y', '%B %d, %Y', '%b %d %Y', '%B %d %Y'):
        try:
            return datetime.strptime(text.replace('/', '-'), fmt).date().isoformat()
        except Exception:
            continue
    return text


def get(url: str):
    req = Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,application/pdf,*/*'})
    with verified_urlopen(req, timeout=45) as response:
        return response.read(), response.headers.get_content_type()


def migrate(c: sqlite3.Connection) -> None:
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute('PRAGMA table_info(daily_court_documents)')}
    for spec in ('document_key TEXT', 'current_version_id TEXT', 'first_seen_at TEXT', 'last_seen_at TEXT'):
        if spec.split()[0] not in cols:
            c.execute(f'ALTER TABLE daily_court_documents ADD COLUMN {spec}')
    cols = {r[1] for r in c.execute('PRAGMA table_info(daily_appearances)')}
    for spec in (
        'document_key TEXT', 'document_version_id TEXT', 'appearance_key TEXT',
        'is_current INTEGER DEFAULT 1', 'superseded_at TEXT', 'superseded_by_appearance_id TEXT',
        'first_seen_at TEXT', 'last_seen_at TEXT'
    ):
        if spec.split()[0] not in cols:
            c.execute(f'ALTER TABLE daily_appearances ADD COLUMN {spec}')
    c.execute('CREATE INDEX IF NOT EXISTS idx_daily_versions_key ON daily_court_document_versions(document_key, is_current)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_daily_apps_key ON daily_appearances(document_key, is_current)')
    # Backfill basic document keys for older databases.
    c.execute("UPDATE daily_court_documents SET document_key=COALESCE(NULLIF(document_key,''),document_id), first_seen_at=COALESCE(first_seen_at,retrieved_at), last_seen_at=COALESCE(last_seen_at,retrieved_at) WHERE document_key IS NULL OR document_key='' OR first_seen_at IS NULL OR last_seen_at IS NULL")
    c.execute("UPDATE daily_appearances SET document_key=COALESCE(NULLIF(document_key,''),document_id), is_current=COALESCE(is_current,1), first_seen_at=COALESCE(first_seen_at, superseded_at, (SELECT retrieved_at FROM daily_court_documents d WHERE d.document_id=daily_appearances.document_id)), last_seen_at=COALESCE(last_seen_at, first_seen_at, superseded_at, (SELECT retrieved_at FROM daily_court_documents d WHERE d.document_id=daily_appearances.document_id)) WHERE document_key IS NULL OR document_key='' OR is_current IS NULL OR first_seen_at IS NULL OR last_seen_at IS NULL")
    c.commit()


def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


def court_slug(name: str) -> str:
    try:
        courts = json.loads((DATA / 'courthouses.json').read_text(encoding='utf-8'))
    except Exception:
        return slug(name)
    hay = str(name or '').lower()
    for court in courts:
        for candidate in (court.get('name'), court.get('city'), str(court.get('slug', '')).replace('-', ' ')):
            if candidate and str(candidate).lower() in hay:
                return court['slug']
    return slug(name)


def ensure_review(c: sqlite3.Connection, entity_type: str, entity_id: str, reason: str, severity: str = 'medium', source_document_id: str | None = None) -> None:
    rid = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{entity_type}:{entity_id}:{reason}'))
    c.execute(
        '''INSERT OR IGNORE INTO review_queue(review_id,entity_type,entity_id,reason,severity,source_document_id,status,created_at)
           VALUES(?,?,?,?,?,?,\'open\',?)''',
        (rid, entity_type, entity_id, reason, severity, source_document_id, now())
    )


def parse_pdf(raw: bytes):
    try:
        from io import BytesIO
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(raw))
        texts = []
        for page in reader.pages:
            try:
                text = page.extract_text(extraction_mode='layout') or ''
            except TypeError:
                text = page.extract_text() or ''
            texts.append(text)
        return '\n'.join(texts), len(reader.pages), 'parsed-layout'
    except Exception as exc:
        return '', 0, f'failed: {exc}'


def discover_pdf_links(html: str, base: str):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    out = []
    for anchor in soup.find_all('a', href=True):
        href = urljoin(base, anchor['href'])
        label = normalize_space(anchor.get_text(' ', strip=True))
        hay = f'{label} {href}'.lower()
        if '.pdf' in href.lower() and (urlparse(href).path.lower().startswith('/courts/') or 'criminal' in hay or 'court' in hay):
            out.append((label or Path(urlparse(href).path).name, href))
    return list(dict.fromkeys(out))


def is_real_judgment_link(title, url, citation=''):
    t = ' '.join(str(title or '').lower().split())
    u = str(url or '').lower()
    if not t or t in NON_JUDGMENT_TITLES or any(x in t for x in NON_JUDGMENT_PHRASES):
        return False
    if citation:
        return True
    if u.endswith('.pdf') or '/doc/' in u or ('/en/bc/' in u and '/doc/' in u):
        return True
    if 'canlii' in u and any(x in t for x in (' v. ', ' v ', ' re ', 'r. v.', 'r v ')):
        return True
    return False


def extract_daily_rows(text: str, level: str, source_url: str, document_id: str, document_key: str, version_id: str, list_date: str = ''):
    """Extract one appearance row per accused from layout-preserved court-list text."""
    rows = []
    seen = set()
    courthouse = ''
    courtroom = ''
    appearance_time = ''
    lines = [normalize_space(x) for x in text.splitlines() if x.strip()]
    for line in lines:
        low = line.lower()
        court_match = re.search(r'(.+?(?:law courts|law court|provincial court|courthouse))(?:-|\s|$)', line, re.I)
        if court_match and len(court_match.group(1)) < 120:
            courthouse = normalize_space(court_match.group(1))
        room_match = re.search(r'\bRoom:\s*([A-Z0-9-]+)', line, re.I)
        if room_match:
            courtroom = room_match.group(1)
        time_match = re.search(r'\b(?:[01]?\d|2[0-3]):[0-5]\d\s*(?:AM|PM)?\b', line, re.I)
        if time_match and ('session commencing' in low or not appearance_time):
            appearance_time = normalize_space(time_match.group(0))

        # Layout extraction yields: row number, file number, accused name, then columns.
        match = re.match(r'^\s*\d+\s+([A-Z0-9-]*\d[A-Z0-9-]*)\s+([A-Za-z][A-Za-z .\'’,-]{2,80}?)(?=\s{2,}|\s+(?:WAR|ROW|RON|N|Y|CCC|CDS|MVA)\b)', line, re.I)
        if not match:
            # Normalized whitespace fallback for short/simple rows.
            match = re.match(r'^\d+\s+([A-Z0-9-]*\d[A-Z0-9-]*)\s+([A-Za-z][A-Za-z .\'’,-]{2,80}?)\s+(?:WAR|ROW|RON|N|Y|CCC|CDS|MVA)\b', line, re.I)
        if not match:
            continue
        file_no = normalize_space(match.group(1))
        name = normalize_space(match.group(2)).strip(' -|:,')
        if not plausible_daily_name(name):
            continue
        stable_bits = '|'.join([list_date.lower(), file_no.lower(), name.lower(), courthouse.lower(), courtroom.lower(), appearance_time.lower()])
        if stable_bits in seen:
            continue
        seen.add(stable_bits)
        appearance_key = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{document_key}|{stable_bits}'))
        appearance_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{version_id}|{appearance_key}'))
        rows.append({
            'appearance_id': appearance_id, 'document_id': document_id, 'list_date': list_date,
            'court_level': level, 'courthouse_name': courthouse, 'courthouse_slug': court_slug(courthouse),
            'courtroom': courtroom, 'appearance_time': appearance_time, 'participant_name': name,
            'court_file_number': file_no, 'appearance_type': 'Scheduled appearance',
            'legal_status': 'scheduled_appearance',
            'allegation_notice': 'Scheduled appearance — allegation not proven.',
            'source_url': source_url, 'verification_state': 'review', 'raw_line': line,
            'document_key': document_key, 'document_version_id': version_id,
            'appearance_key': appearance_key, 'is_current': 1, 'superseded_at': None,
            'superseded_by_appearance_id': None, 'first_seen_at': None, 'last_seen_at': None,
        })
    return rows


def plausible_daily_name(name: str) -> bool:
    value = normalize_space(name)
    low = value.lower()
    if not (3 <= len(value) <= 90) or any(ch.isdigit() for ch in value):
        return False
    if any(term in low for term in ('file number', 'public access', 'court list', 'session commencing', 'location of offence')):
        return False
    words = [w for w in re.split(r'\s+', value.replace(',', ' ')) if w]
    return 2 <= len(words) <= 8 and any(',' in value for _ in [0])


def store_daily_document(c: sqlite3.Connection, title: str, url: str, body: bytes, ctype: str):
    digest = sha(body)
    ext = '.pdf' if 'pdf' in ctype or '.pdf' in url.lower() else '.bin'
    archive_path = ARCHIVE / 'daily-court-lists' / f'{datetime.now():%Y-%m-%d}-{digest[:12]}{ext}'
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if not archive_path.exists():
        archive_path.write_bytes(body)
    text, pages, status = parse_pdf(body) if ext == '.pdf' else ('', 0, 'indexed')
    match = re.search(r'20\d{2}[-/][01]?\d[-/][0-3]?\d|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+20\d{2}', text, re.I)
    list_date = normalize_list_date(match.group(0) if match else datetime.now().date().isoformat())
    level = 'Supreme Court' if 'supreme' in f'{title} {url}'.lower() else 'Provincial Court'
    stamp = now()

    head = c.execute('SELECT document_id, document_key, current_version_id FROM daily_court_documents WHERE source_url=?', (url,)).fetchone()
    document_id = head['document_id'] if head else str(uuid.uuid5(uuid.NAMESPACE_URL, f'daily-head:{url}'))
    document_key = (head['document_key'] if head and head['document_key'] else document_id)
    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{document_key}|{digest}'))
    version_exists = c.execute('SELECT version_id FROM daily_court_document_versions WHERE version_id=?', (version_id,)).fetchone() is not None

    previous_current = c.execute('SELECT version_id FROM daily_court_document_versions WHERE document_key=? AND is_current=1', (document_key,)).fetchall()
    if not version_exists:
        c.execute('UPDATE daily_court_document_versions SET is_current=0, superseded_at=? WHERE document_key=? AND is_current=1', (stamp, document_key))
        c.execute('UPDATE daily_appearances SET is_current=0, superseded_at=? WHERE document_key=? AND is_current=1', (stamp, document_key))

    c.execute(
        '''INSERT INTO daily_court_documents(document_id,court_level,list_date,title,source_url,local_path,sha256,retrieved_at,parse_status,raw_text,page_count,document_key,current_version_id,first_seen_at,last_seen_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(source_url) DO UPDATE SET
             court_level=excluded.court_level,list_date=excluded.list_date,title=excluded.title,
             local_path=excluded.local_path,sha256=excluded.sha256,retrieved_at=excluded.retrieved_at,
             parse_status=excluded.parse_status,raw_text=excluded.raw_text,page_count=excluded.page_count,
             document_key=excluded.document_key,current_version_id=excluded.current_version_id,
             first_seen_at=COALESCE(daily_court_documents.first_seen_at,excluded.first_seen_at),
             last_seen_at=excluded.last_seen_at''',
        (document_id, level, list_date, title, url, str(archive_path.relative_to(ROOT)).replace('\\', '/'), digest, stamp, status, text, pages, document_key, version_id, stamp, stamp)
    )

    c.execute(
        '''INSERT OR IGNORE INTO daily_court_document_versions(version_id,document_key,source_url,court_level,list_date,title,local_path,sha256,retrieved_at,parse_status,raw_text,page_count,is_current,superseded_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,NULL)''',
        (version_id, document_key, url, level, list_date, title, str(archive_path.relative_to(ROOT)).replace('\\', '/'), digest, stamp, status, text, pages)
    )
    c.execute('UPDATE daily_court_document_versions SET is_current=1, superseded_at=NULL WHERE version_id=?', (version_id,))

    rows = extract_daily_rows(text, level, url, document_id, document_key, version_id, list_date)
    for row in rows:
        row['first_seen_at'] = stamp
        row['last_seen_at'] = stamp
        c.execute(
            '''INSERT OR IGNORE INTO daily_appearances(
                 appearance_id,document_id,list_date,court_level,courthouse_name,courthouse_slug,courtroom,
                 appearance_time,participant_name,court_file_number,appearance_type,legal_status,
                 allegation_notice,source_url,verification_state,raw_line,document_key,document_version_id,
                 appearance_key,is_current,superseded_at,superseded_by_appearance_id,first_seen_at,last_seen_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(appearance_id) DO UPDATE SET
                 document_id=excluded.document_id,list_date=excluded.list_date,court_level=excluded.court_level,
                 courthouse_name=excluded.courthouse_name,courthouse_slug=excluded.courthouse_slug,courtroom=excluded.courtroom,
                 appearance_time=excluded.appearance_time,participant_name=excluded.participant_name,
                 court_file_number=excluded.court_file_number,appearance_type=excluded.appearance_type,
                 legal_status=excluded.legal_status,allegation_notice=excluded.allegation_notice,
                 source_url=excluded.source_url,verification_state=excluded.verification_state,raw_line=excluded.raw_line,
                 document_key=excluded.document_key,document_version_id=excluded.document_version_id,
                 appearance_key=excluded.appearance_key,is_current=1,superseded_at=NULL,
                 superseded_by_appearance_id=NULL,last_seen_at=excluded.last_seen_at''',
            (
                row['appearance_id'], row['document_id'], row['list_date'], row['court_level'], row['courthouse_name'], row['courthouse_slug'], row['courtroom'],
                row['appearance_time'], row['participant_name'], row['court_file_number'], row['appearance_type'], row['legal_status'],
                row['allegation_notice'], row['source_url'], row['verification_state'], row['raw_line'], row['document_key'], row['document_version_id'],
                row['appearance_key'], row['is_current'], row['superseded_at'], row['superseded_by_appearance_id'], row['first_seen_at'], row['last_seen_at']
            )
        )
        c.execute('''UPDATE daily_appearances
                     SET superseded_by_appearance_id=?, is_current=0, superseded_at=COALESCE(superseded_at,?)
                     WHERE document_key=? AND appearance_key=? AND appearance_id<>?''',
                  (row['appearance_id'], stamp, document_key, row['appearance_key'], row['appearance_id']))
        ensure_review(c, 'daily_appearance', row['appearance_id'], 'Confirm parsed court-list appearance', 'medium', document_id)

    return {
        'document_id': document_id,
        'document_key': document_key,
        'version_id': version_id,
        'new_version': not version_exists,
        'replaced_versions': len(previous_current) if not version_exists else 0,
        'level': level,
        'list_date': list_date,
        'appearance_count': len(rows),
    }


def collect_daily(c: sqlite3.Connection):
    links = []
    for level, index_url in DAILY_INDEXES:
        try:
            raw, _ = get(index_url)
            html = raw.decode('utf-8', 'replace')
            for title, url in discover_pdf_links(html, index_url):
                links.append((f'{level}: {title}', url))
        except Exception as exc:
            print(f'Daily index fetch failed: {index_url}: {exc}', file=sys.stderr)
    links = list(dict.fromkeys(links))
    if not links:
        print('Daily court list discovery found 0 PDFs. Source indexes may have changed.', file=sys.stderr)
    else:
        print(f'Daily court list discovery found {len(links)} PDFs.')
    added = 0
    appearances = 0
    empty_parses = 0
    for title, url in links:
        try:
            body, ctype = get(url)
        except Exception as exc:
            print(f'Daily list fetch failed: {url}: {exc}', file=sys.stderr)
            continue
        result = store_daily_document(c, title, url, body, ctype)
        added += 1 if result['new_version'] else 0
        appearances += result['appearance_count']
        if result['appearance_count'] == 0:
            empty_parses += 1
            print(f'Daily list parsed 0 appearances: {url}', file=sys.stderr)
    c.commit()
    print(f'Daily court lists: {appearances} appearances from {len(links)} PDFs; {empty_parses} empty parses.')
    return added, appearances


def collect_judgments(c: sqlite3.Connection):
    from bs4 import BeautifulSoup
    count = 0
    for row in c.execute('SELECT judgment_id,case_title,source_url,citation FROM published_judgments').fetchall():
        if not is_real_judgment_link(row['case_title'], row['source_url'], row['citation']):
            c.execute("DELETE FROM review_queue WHERE entity_type='published_judgment' AND entity_id=?", (row['judgment_id'],))
            c.execute('DELETE FROM published_judgments WHERE judgment_id=?', (row['judgment_id'],))
    c.commit()
    for level, index_url in JUDGMENT_SOURCES:
        try:
            raw, _ = get(index_url)
        except Exception as exc:
            print(f'Judgment index fetch failed: {index_url}: {exc}', file=sys.stderr)
            continue
        soup = BeautifulSoup(raw, 'html.parser')
        for anchor in soup.find_all('a', href=True):
            title = normalize_space(anchor.get_text(' ', strip=True))
            url = urljoin(index_url, anchor['href'])
            if not title or url == index_url:
                continue
            hay = f'{title} {url}'.lower()
            if not any(x in hay for x in ('canlii', 'judgment', 'decision', '.pdf', '/doc/')):
                continue
            citation = ''
            match = re.search(r'\b(20\d{2})\s+(BCPC|BCSC|BCCA)\s+\d+\b', title, re.I)
            if match:
                citation = match.group(0).upper()
            if not is_real_judgment_link(title, url, citation):
                continue
            date_match = re.search(r'(20\d{2}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+20\d{2})', title, re.I)
            decision_date = date_match.group(0) if date_match else ''
            jid = str(uuid.uuid5(uuid.NAMESPACE_URL, url))
            c.execute(
                '''INSERT INTO published_judgments(judgment_id,court_level,case_title,citation,decision_date,source_url,source_index_url,document_type,verification_state,retrieved_at,raw_metadata)
                   VALUES(?,?,?,?,?,?,?,?,\'review\',?,?)
                   ON CONFLICT(source_url) DO UPDATE SET
                     case_title=excluded.case_title,citation=excluded.citation,
                     decision_date=excluded.decision_date,retrieved_at=excluded.retrieved_at,
                     raw_metadata=excluded.raw_metadata''',
                (jid, level, title, citation, decision_date, url, index_url, 'PDF' if '.pdf' in url.lower() else 'HTML', now(), json.dumps({'linkText': title}, ensure_ascii=False))
            )
            ensure_review(c, 'published_judgment', jid, 'Verify judgment outcome, sentence and publication restrictions', 'high')
            count += 1
    c.commit()
    return count


def normalize_status(value):
    val = str(value or '').strip().lower().replace(' ', '_')
    aliases = {'appearance': 'scheduled_appearance', 'scheduled': 'scheduled_appearance', 'charge': 'charged', 'charges_stayed': 'stayed', 'not_guilty': 'acquitted', 'withdrawn/dismissed': 'withdrawn'}
    return aliases.get(val, val or 'unknown')


def cso_value(row, *names):
    """Return the first populated value across canonical and legacy CSO columns."""
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ''


def import_cso(c: sqlite3.Connection, files):
    total = errors = 0
    for path in files:
        file_path = Path(path)
        if not file_path.exists():
            continue
        body = file_path.read_bytes()
        digest = sha(body)
        batch_id = str(uuid.uuid5(uuid.NAMESPACE_URL, digest))
        if c.execute('SELECT 1 FROM cso_import_batches WHERE sha256=?', (digest,)).fetchone():
            continue
        batch_rows = batch_errors = 0
        with file_path.open('r', encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                try:
                    file_no = cso_value(row, 'court_file_number', 'file_number')
                    court = cso_value(row, 'courthouse', 'court', 'location')
                    source = cso_value(row, 'source_url') or CSO_HOME
                    if not file_no:
                        raise ValueError('court_file_number is required')
                    case_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'CSO|{file_no}|{court}'))
                    status = normalize_status(cso_value(row, 'legal_status', 'status'))
                    final_value = cso_value(row, 'final_outcome', 'outcome')
                    final = normalize_status(final_value) if final_value else None
                    verified = str(row.get('verified') or '').lower() in ('1', 'true', 'yes')
                    c.execute(
                        '''INSERT INTO cases(case_id,court_file_number,court_level,courthouse_slug,case_title,legal_status,final_outcome,outcome_date,verification_state,source_url,retrieved_at,notes)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(court_file_number,courthouse_slug) DO UPDATE SET
                             legal_status=excluded.legal_status,final_outcome=excluded.final_outcome,
                             outcome_date=excluded.outcome_date,verification_state=excluded.verification_state,
                             source_url=excluded.source_url,retrieved_at=excluded.retrieved_at,notes=excluded.notes''',
                        (case_id, file_no, cso_value(row, 'court_level') or 'Provincial Court', court_slug(court), cso_value(row, 'case_title'), status, final, cso_value(row, 'outcome_date'), 'verified' if verified else 'review', source, now(), cso_value(row, 'notes') or 'Imported from controlled CSO index')
                    )
                    name = cso_value(row, 'participant_name', 'person_name', 'name')
                    if name:
                        person_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'PERSON|' + re.sub(r'\W+', ' ', name.lower()).strip()))
                        c.execute('INSERT OR IGNORE INTO people(person_id,display_name,normalized_name,review_required,created_at,updated_at) VALUES(?,?,?,?,?,?)', (person_id, name, re.sub(r'\W+', ' ', name.lower()).strip(), 0 if verified else 1, now(), now()))
                        c.execute('INSERT OR IGNORE INTO case_people(case_id,person_id,role) VALUES(?,?,?)', (case_id, person_id, cso_value(row, 'role') or 'accused'))
                    offence = cso_value(row, 'offence', 'offence_text', 'charge')
                    if offence:
                        charge_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{case_id}|CSO|{offence.lower()}'))
                        c.execute('''INSERT INTO charges(charge_id,case_id,offence_text,charge_status,disposition,disposition_date)
                                     VALUES(?,?,?,?,?,?)
                                     ON CONFLICT(charge_id) DO UPDATE SET offence_text=excluded.offence_text,
                                       charge_status=excluded.charge_status,disposition=excluded.disposition,
                                       disposition_date=excluded.disposition_date''',
                                  (charge_id, case_id, offence, 'alleged' if status in ('charged','scheduled_appearance','unknown') else 'resolved', final, cso_value(row, 'outcome_date')))
                    event_date = cso_value(row, 'event_date', 'appearance_date')
                    if event_date:
                        event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{case_id}|{event_date}|{row.get("event_type") or status}'))
                        c.execute('INSERT OR IGNORE INTO case_events(event_id,case_id,event_type,event_date,courthouse_slug,description,verification_state) VALUES(?,?,?,?,?,?,?)', (event_id, case_id, cso_value(row, 'event_type') or status, event_date, court_slug(court), cso_value(row, 'event_description'), 'verified' if verified else 'review'))
                    if not verified:
                        ensure_review(c, 'case', case_id, 'Verify CSO case identity and current status', 'high')
                    batch_rows += 1
                    total += 1
                except Exception as exc:
                    batch_errors += 1
                    errors += 1
                    print(f'{file_path.name}: {exc}', file=sys.stderr)
        c.execute('INSERT INTO cso_import_batches VALUES(?,?,?,?,?,?)', (batch_id, str(file_path), digest, now(), batch_rows, batch_errors))
        c.commit()
    return total, errors


def export(c: sqlite3.Connection):
    DATA.mkdir(exist_ok=True)
    appearances = [dict(r) for r in c.execute('''
        SELECT * FROM (
          SELECT a.*,
                 COALESCE(v.local_path,d.local_path,'') AS local_path,
                 COALESCE(v.title,d.title,'') AS source_title,
                 ROW_NUMBER() OVER (
            PARTITION BY COALESCE(NULLIF(a.appearance_key,''), lower(COALESCE(a.list_date,'')) || '|' || lower(COALESCE(a.court_file_number,'')) || '|' || lower(COALESCE(a.participant_name,'')) || '|' || lower(COALESCE(a.courthouse_name,'')) || '|' || lower(COALESCE(a.appearance_time,'')))
            ORDER BY COALESCE(a.last_seen_at, a.first_seen_at, a.superseded_at, '') DESC,
                     COALESCE(a.is_current,0) DESC
          ) AS catalogue_rank
          FROM daily_appearances a
          LEFT JOIN daily_court_document_versions v ON v.version_id=a.document_version_id
          LEFT JOIN daily_court_documents d ON d.document_id=a.document_id
        ) WHERE catalogue_rank=1
        ORDER BY list_date DESC, appearance_time, courthouse_name, participant_name
    ''')]
    # Daily court-list PDFs generally identify the accused and court file, but not the offence.
    # Link charges from normalized case records using a transparent evidence hierarchy.
    # A court-file-only match is retained as Non Verified so useful charge context is shown without
    # implying that the charge has been confirmed for the named appearance.
    charge_map = {}
    try:
        for row in c.execute("""
            SELECT ca.case_id, ca.court_file_number, ca.courthouse_slug, ca.court_level,
                   ca.opened_date, ca.closed_date, ca.verification_state, ca.source_url,
                   ch.offence_text, ch.charge_status, ch.disposition,
                   GROUP_CONCAT(DISTINCT p.display_name) AS linked_names
            FROM charges ch
            JOIN cases ca ON ca.case_id=ch.case_id
            LEFT JOIN case_people cp ON cp.case_id=ca.case_id AND lower(COALESCE(cp.role,'accused')) IN ('accused','defendant','appellant')
            LEFT JOIN people p ON p.person_id=cp.person_id
            WHERE trim(COALESCE(ca.court_file_number,''))<>''
              AND trim(COALESCE(ch.offence_text,''))<>''
            GROUP BY ca.case_id, ch.charge_id
        """):
            key = re.sub(r'[^a-z0-9]', '', str(row['court_file_number'] or '').lower())
            if not key:
                continue
            item = {
                'case_id': row['case_id'],
                'offence': normalize_space(row['offence_text']),
                'status': normalize_space(row['charge_status']),
                'disposition': normalize_space(row['disposition']),
                'courthouse_slug': normalize_space(row['courthouse_slug']).lower(),
                'court_level': normalize_space(row['court_level']).lower(),
                'opened_date': normalize_space(row['opened_date']),
                'closed_date': normalize_space(row['closed_date']),
                'verification_state': normalize_space(row['verification_state']),
                'source_url': normalize_space(row['source_url']),
                'linked_names': [normalize_space(x) for x in str(row['linked_names'] or '').split(',') if normalize_space(x)],
            }
            if item['offence'] and item not in charge_map.setdefault(key, []):
                charge_map[key].append(item)
    except sqlite3.OperationalError:
        charge_map = {}

    def norm_name(value):
        return re.sub(r'[^a-z0-9 ]', '', normalize_space(value).lower()).strip()

    def norm_place(value):
        return re.sub(r'[^a-z0-9]', '', normalize_space(value).lower())

    rank_value = {'Confirmed': 5, 'Likely': 4, 'Possible': 3, 'Non Verified': 2, 'Charge Not Available': 1}
    for appearance in appearances:
        key = re.sub(r'[^a-z0-9]', '', str(appearance.get('court_file_number') or '').lower())
        candidates = charge_map.get(key, [])
        app_name = norm_name(appearance.get('participant_name'))
        app_tokens = set(app_name.split())
        app_place = norm_place(appearance.get('courthouse_slug') or appearance.get('courthouse_name'))
        app_level = normalize_space(appearance.get('court_level')).lower()
        app_date = normalize_space(appearance.get('list_date'))
        linked = []
        for item in candidates:
            names = [norm_name(x) for x in item.get('linked_names', [])]
            exact_name = bool(app_name and app_name in names)
            surname_match = bool(app_tokens and any(app_tokens & set(x.split()) and app_name.split()[-1:] == x.split()[-1:] for x in names))
            place_match = bool(app_place and item.get('courthouse_slug') and (app_place in norm_place(item['courthouse_slug']) or norm_place(item['courthouse_slug']) in app_place))
            level_match = bool(app_level and item.get('court_level') and app_level == item['court_level'])
            date_match = bool(app_date and ((item.get('opened_date') and item['opened_date'] <= app_date) or (item.get('closed_date') and item['closed_date'] >= app_date)))
            if exact_name and (place_match or level_match or date_match):
                tier = 'Confirmed' if place_match and (level_match or date_match) else 'Likely'
            elif exact_name:
                tier = 'Likely'
            elif surname_match or place_match or level_match or date_match:
                tier = 'Possible'
            else:
                tier = 'Non Verified'
            evidence = ['exact court file']
            if exact_name: evidence.append('accused name')
            elif surname_match: evidence.append('partial name')
            if place_match: evidence.append('courthouse')
            if level_match: evidence.append('court level')
            if date_match: evidence.append('compatible date')
            linked.append({**item, 'confidence_tier': tier, 'match_evidence': evidence})
        linked.sort(key=lambda x: (-rank_value.get(x['confidence_tier'], 0), x['offence'].lower()))
        appearance['linked_charges'] = linked
        appearance['charge_confidence'] = linked[0]['confidence_tier'] if linked else 'Charge Not Available'
        appearance['alleged_charges'] = ' · '.join(dict.fromkeys(x['offence'] for x in linked))
        appearance['charge_notice'] = (
            f"{appearance['charge_confidence']} charge link. Matched by: {', '.join(linked[0]['match_evidence'])}."
            if linked else
            'No charge information  linked to this appearance.'
        )

    appearance_meta = write_paged_records(DATA / 'daily-court-lists.json', 'appearances', appearances, page_size=5000, meta={
        'generatedAt': now(),
        'notice': 'Scheduled appearance — allegation not proven.',
        'summary': {
            'cataloguedAppearances': len(appearances),
            'currentAppearances': c.execute('SELECT COUNT(*) FROM daily_appearances WHERE COALESCE(is_current,1)=1').fetchone()[0],
            'historicalAppearanceRows': c.execute('SELECT COUNT(*) FROM daily_appearances').fetchone()[0],
            'distinctCataloguedNames': c.execute("SELECT COUNT(DISTINCT lower(trim(participant_name))) FROM daily_appearances WHERE trim(COALESCE(participant_name,''))<>''").fetchone()[0],
            'currentDocuments': c.execute('SELECT COUNT(*) FROM daily_court_documents').fetchone()[0],
            'documentVersions': c.execute('SELECT COUNT(*) FROM daily_court_document_versions').fetchone()[0],
        },
        'documents': [dict(r) for r in c.execute('''SELECT document_id,document_key,current_version_id,court_level,list_date,title,source_url,local_path,retrieved_at,parse_status,page_count,first_seen_at,last_seen_at
                                                    FROM daily_court_documents ORDER BY retrieved_at DESC LIMIT 500''')],
        'history': [dict(r) for r in c.execute('''SELECT document_key,version_id,source_url,list_date,title,sha256,retrieved_at,is_current,superseded_at
                                                  FROM daily_court_document_versions ORDER BY retrieved_at DESC LIMIT 2000''')],
    })
    appearance_files = [DATA / 'daily-court-lists.json', *[DATA / f'daily-court-lists-page-{i}.json' for i in range(2, int(appearance_meta['pageCount']) + 1)]]
    source_stamp = str(max((path.stat().st_mtime_ns for path in appearance_files if path.exists()), default=0))
    refresh_appearance_search_cache(c, appearances, source_stamp)
    judgments = [dict(r) for r in c.execute('SELECT * FROM published_judgments ORDER BY COALESCE(decision_date,retrieved_at) DESC LIMIT 5000')]
    cases = [dict(r) for r in c.execute("SELECT * FROM cases WHERE source_url LIKE '%justice.gov.bc.ca/cso%' OR notes LIKE '%CSO%' ORDER BY retrieved_at DESC LIMIT 5000")]
    write_json_atomic(DATA / 'published-judgments.json', {'generatedAt': now(), 'notice': 'Outcome fields require verification against the judgment.', 'judgments': judgments})
    write_json_atomic(DATA / 'cso-cases.json', {'generatedAt': now(), 'notice': 'CSO index records require case-specific verification.', 'cases': cases})
    print(f"Exported {appearance_meta['totalRecords']} appearances across {appearance_meta['pageCount']} page(s), {len(judgments)} judgments, {len(cases)} CSO cases.")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('command', choices=['setup', 'daily', 'judgments', 'cso', 'all', 'export'])
    ap.add_argument('files', nargs='*')
    args = ap.parse_args(argv)
    c = db()
    if args.command == 'setup':
        print('Justice source schema ready.')
    elif args.command == 'daily':
        print('Daily lists:', collect_daily(c)); export(c)
    elif args.command == 'judgments':
        print('Judgments:', collect_judgments(c)); export(c)
    elif args.command == 'cso':
        files = args.files or list((IMPORTS / 'cso').glob('*.csv'))
        print('CSO:', import_cso(c, files)); export(c)
    elif args.command == 'all':
        print('Daily lists:', collect_daily(c))
        print('Judgments:', collect_judgments(c))
        print('CSO:', import_cso(c, args.files or list((IMPORTS / 'cso').glob('*.csv'))))
        export(c)
    elif args.command == 'export':
        export(c)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
