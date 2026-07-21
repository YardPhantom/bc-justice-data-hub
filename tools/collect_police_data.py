#!/usr/bin/env python3
"""Collect and index official BC police use-of-force and police-resource reports."""
from __future__ import annotations
import hashlib, json, re, sqlite3, time, uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin
from urllib.error import HTTPError, URLError
from urllib.request import Request

from export_utils import write_json_atomic
from secure_http import verified_urlopen

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'database' / 'bc_justice.db'
DATA = ROOT / 'data'
ARCH = ROOT / 'imports' / 'police'
DISCOVERY_CACHE = ARCH / 'discovery-cache.json'
INDEX_URL = 'https://www2.gov.bc.ca/gov/content/justice/criminal-justice/policing-in-bc/publications-statistics-legislation/crime-police-resource-statistics'
UA = 'BCJusticeDataHub/0.8.4 (+private local research)'
REPORT_TERMS = ('use of force', 'firearm use', 'intermediate weapon use', 'conducted energy weapon use', 'police service dog data', 'police resources in british columbia')

MULTI_YEAR_METRICS = (
    ('Population per officer', 'people per officer', ('population per officer', 'population/officer')),
    ('Cases per officer', 'cases per officer', ('cases per officer', 'case load per officer')),
    ('Authorized police strength', 'officers', ('authorized police strength', 'authorized strength')),
    ('Police officers', 'officers', ('police officers', 'sworn officers', 'officer strength')),
    ('Police expenditures', 'dollars', ('police expenditures', 'policing expenditures', 'police costs', 'policing costs', 'expenditures')),
    ('Criminal Code cases', 'cases', ('criminal code cases', 'criminal code offences', 'criminal cases')),
    ('Population served', 'people', ('population served', 'policed population', 'service population')),
)


def numeric_tokens(line):
    return re.findall(r'(?<![A-Za-z])\$?[0-9][0-9,]*(?:\.[0-9]+)?%?', line)


def metric_from_label(label):
    low = ' '.join(label.lower().split())
    for metric, unit, terms in MULTI_YEAR_METRICS:
        if any(term in low for term in terms):
            return metric, unit
    return None


def extract_multi_year_tables(report_id, url, text):
    lines = [' '.join(x.split()) for x in text.splitlines() if x.strip()]
    out = []
    seen = set()
    for i, line in enumerate(lines):
        years = re.findall(r'\b20(?:0\d|1\d|2\d|3\d)\b', line)
        header_end = i
        if len(years) < 2 and re.fullmatch(r'20\d{2}', line):
            vertical = []
            j = i
            while j < len(lines) and j < i + 8 and re.fullmatch(r'20\d{2}', lines[j]):
                vertical.append(lines[j])
                j += 1
            if len(vertical) >= 2:
                years = vertical
                header_end = j - 1
        years = list(dict.fromkeys(years))
        if not 2 <= len(years) <= 8:
            continue
        for row in lines[header_end + 1:header_end + 31]:
            found = metric_from_label(row)
            if not found:
                continue
            metric, unit = found
            vals = numeric_tokens(row)
            if vals and re.fullmatch(r'20\d{2}', vals[0]) and len(vals) == len(years) + 1:
                vals = vals[1:]
            if len(vals) != len(years):
                continue
            for yr, raw_val in zip(years, vals):
                val = number(raw_val)
                if val is None:
                    continue
                key = (yr, metric, val, row)
                if key in seen:
                    continue
                seen.add(key)
                source = f'Year columns: {" | ".join(years)}; row: {row}'[:900]
                out.append({'observation_id': uid(report_id, 'multi-year', yr, metric, row), 'report_id': report_id, 'geography': 'British Columbia', 'police_service': '', 'year': yr, 'subject_area': 'staffing-spending', 'metric': metric, 'value': val, 'unit': unit, 'source_line': source, 'confidence': .68, 'verification_state': 'review', 'source_url': url})
    return out


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def uid(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, '|'.join(map(str, parts))))


def fetch(url, *, attempts=4, timeout=75):
    """Fetch an official source with verified TLS and retry temporary gateway failures."""
    delays = (0, 5, 15, 30)
    last_error = None
    for attempt in range(1, attempts + 1):
        if delays[attempt - 1]:
            print(f'  Retry {attempt}/{attempts} in {delays[attempt - 1]} seconds...')
            time.sleep(delays[attempt - 1])
        req = Request(url, headers={
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/pdf,*/*',
            'Accept-Language': 'en-CA,en;q=0.9',
            'Cache-Control': 'no-cache',
        })
        try:
            with verified_urlopen(req, timeout=timeout) as response:
                return response.read(), response.headers.get_content_type()
        except HTTPError as exc:
            last_error = exc
            if exc.code not in (408, 425, 429, 500, 502, 503, 504) or attempt == attempts:
                raise
            print(f'  Temporary HTTP {exc.code} from {url}')
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == attempts:
                raise
            print(f'  Temporary network error from {url}: {exc}')
    raise last_error


def setup(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS police_reports(
      report_id TEXT PRIMARY KEY,title TEXT,report_year TEXT,report_type TEXT,source_url TEXT UNIQUE,
      local_path TEXT,sha256 TEXT,retrieved_at TEXT,parse_status TEXT,summary TEXT,raw_text TEXT
    );
    CREATE TABLE IF NOT EXISTS police_observations(
      observation_id TEXT PRIMARY KEY,report_id TEXT,geography TEXT,police_service TEXT,year TEXT,
      subject_area TEXT,metric TEXT,value REAL,unit TEXT,source_line TEXT,confidence REAL,
      verification_state TEXT DEFAULT 'review',source_url TEXT,
      FOREIGN KEY(report_id) REFERENCES police_reports(report_id)
    );
    CREATE INDEX IF NOT EXISTS idx_police_obs_type ON police_observations(subject_area,year);
    CREATE INDEX IF NOT EXISTS idx_police_obs_geo ON police_observations(geography,police_service);
    ''')
    c.commit()


def report_type(title):
    t = title.lower()
    if 'police resources' in t:
        return 'staffing-spending'
    if 'firearm' in t:
        return 'firearms'
    if 'conducted energy' in t:
        return 'conducted-energy-weapons'
    if 'service dog' in t:
        return 'police-dogs'
    if 'intermediate weapon' in t:
        return 'intermediate-weapons'
    return 'overall-use-of-force'


def pdf_text(raw):
    try:
        from pypdf import PdfReader
        text = '\n'.join((p.extract_text() or '') for p in PdfReader(BytesIO(raw)).pages)
        return text, 'parsed'
    except Exception as exc:
        return '', f'failed: {exc}'


def _load_discovery_cache():
    try:
        payload = json.loads(DISCOVERY_CACHE.read_text(encoding='utf-8'))
        rows = [(str(x['title']), str(x['url'])) for x in payload.get('reports', []) if x.get('title') and x.get('url')]
        if rows:
            print(f'Using cached police report list: {len(rows)} report(s)')
        return rows
    except Exception:
        return []


def _save_discovery_cache(rows):
    write_json_atomic(DISCOVERY_CACHE, {'savedAt': now(), 'sourcePage': INDEX_URL, 'reports': [{'title': t, 'url': u} for t, u in rows]})


def discover():
    from bs4 import BeautifulSoup
    raw, _ = fetch(INDEX_URL)
    soup = BeautifulSoup(raw, 'html.parser')
    found = []
    for anchor in soup.find_all('a', href=True):
        title = ' '.join(anchor.get_text(' ', strip=True).split())
        low = title.lower()
        if title and any(term in low for term in REPORT_TERMS) and ('pdf' in low or anchor['href'].lower().endswith('.pdf')):
            found.append((title, urljoin(INDEX_URL, anchor['href'])))
    rows = list(dict.fromkeys(found))
    if rows:
        _save_discovery_cache(rows)
    return rows


def number(s):
    try:
        return float(s.replace(',', '').replace('$', '').replace('%', ''))
    except Exception:
        return None


def extract_observations(report_id, title, url, text):
    typ = report_type(title)
    year_match = re.search(r'\b(20\d{2})\b', title) or re.search(r'\b(20\d{2})\b', text[:3000])
    year = year_match.group(1) if year_match else ''
    observations = []
    lines = [' '.join(x.split()) for x in text.splitlines() if x.strip()]
    patterns = [
        ('firearms', 'Firearm discharges', r'(?i)firearm(?:s)?\s+(?:were\s+)?discharg(?:e|ed|es)[^\d]{0,35}([\d,]+)'),
        ('firearms', 'Firearm displays', r'(?i)firearm(?:s)?\s+(?:were\s+)?display(?:ed|s)[^\d]{0,35}([\d,]+)'),
        ('conducted-energy-weapons', 'CEW discharges', r'(?i)(?:CEW|conducted energy weapon)[^\n]{0,45}discharg(?:e|ed|es)[^\d]{0,25}([\d,]+)'),
        ('police-dogs', 'Police dog bites', r'(?i)(?:police service dog|PSD)[^\n]{0,45}(?:bite|bitten|apprehension)[^\d]{0,25}([\d,]+)'),
        ('intermediate-weapons', 'Intermediate weapon uses', r'(?i)intermediate weapon[^\n]{0,45}(?:use|deployment|incident)[^\d]{0,25}([\d,]+)'),
        ('overall-use-of-force', 'Use-of-force incidents', r'(?i)(?:use.of.force|reportable force)[^\n]{0,50}(?:incident|report)[^\d]{0,25}([\d,]+)'),
        ('staffing-spending', 'Authorized police strength', r'(?i)authorized strength[^\d]{0,30}([\d,]+)'),
        ('staffing-spending', 'Police officers', r'(?i)(?:total )?(?:sworn )?police officers[^\d]{0,30}([\d,]+)'),
        ('staffing-spending', 'Police expenditures', r'(?i)(?:total )?(?:police|policing) (?:costs|expenditures)[^$\d]{0,30}(\$?[\d,]+(?:\.\d+)?)'),
        ('staffing-spending', 'Population per officer', r'(?i)population per (?:authorized )?(?:police )?officer[^\d]{0,20}([\d,]+)'),
    ]
    seen = set()
    for line in lines:
        for subject, metric, pat in patterns:
            match = re.search(pat, line)
            if not match:
                continue
            val = number(match.group(1))
            key = (subject, metric, val, line)
            if val is None or key in seen:
                continue
            seen.add(key)
            unit = 'dollars' if 'expenditure' in metric.lower() else 'count'
            observations.append({'observation_id': uid(report_id, metric, line), 'report_id': report_id, 'geography': 'British Columbia', 'police_service': '', 'year': year, 'subject_area': subject, 'metric': metric, 'value': val, 'unit': unit, 'source_line': line[:900], 'confidence': .72, 'verification_state': 'review', 'source_url': url})
    if typ == 'staffing-spending':
        observations.extend(extract_multi_year_tables(report_id, url, text))
        row_re = re.compile(r"^([A-Za-z][A-Za-z .'’/&()-]{2,45}?)\s+([\d,]{3,})\s+([\d,]{1,4})\s+([\d,]{1,8})\s+([\d,]{1,5})\s+([\d,]{1,5})$")
        for line in lines:
            match = row_re.match(line)
            if not match:
                continue
            service = match.group(1).strip()
            vals = [number(x) for x in match.groups()[1:]]
            labels = [('Population served', 'people'), ('Police officers / authorized strength', 'officers'), ('Criminal Code cases', 'cases'), ('Population per officer', 'people per officer'), ('Cases per officer', 'cases per officer')]
            for (metric, unit), val in zip(labels, vals):
                observations.append({'observation_id': uid(report_id, service, metric, year), 'report_id': report_id, 'geography': service, 'police_service': service, 'year': year, 'subject_area': 'staffing-spending', 'metric': metric, 'value': val, 'unit': unit, 'source_line': line[:900], 'confidence': .58, 'verification_state': 'review', 'source_url': url})
    return observations


def collect():
    ARCH.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    setup(conn)
    try:
        print('Discovering official BC police reports...')
        reports = discover()
        print(f'Police report discovery: {len(reports)} report(s)')
    except Exception as exc:
        print('Police report discovery failed after retries:', exc)
        reports = _load_discovery_cache()
        if not reports:
            print('No discovery cache is available; preserving previously imported police data.')
    for title, url in reports:
        try:
            raw, _ = fetch(url)
        except Exception as exc:
            print('Police report fetch failed:', url, exc)
            continue
        digest = hashlib.sha256(raw).hexdigest()
        path = ARCH / f'{digest[:16]}.pdf'
        path.write_bytes(raw)
        text, status = pdf_text(raw)
        report_id = uid(url)
        typ = report_type(title)
        year_match = re.search(r'\b20\d{2}\b', title)
        year = year_match.group(0) if year_match else ''
        summary = ' '.join(text.split())[:900]
        observations = extract_observations(report_id, title, url, text)
        conn.execute(f'SAVEPOINT police_{report_id.replace("-", "_")}')
        try:
            conn.execute('''INSERT INTO police_reports VALUES(?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(source_url) DO UPDATE SET
                              title=excluded.title,report_year=excluded.report_year,report_type=excluded.report_type,
                              local_path=excluded.local_path,sha256=excluded.sha256,retrieved_at=excluded.retrieved_at,
                              parse_status=excluded.parse_status,summary=excluded.summary,raw_text=excluded.raw_text''',
                         (report_id, title, year, typ, url, str(path.relative_to(ROOT)).replace('\\', '/'), digest, now(), status, summary, text))
            conn.execute('DELETE FROM police_observations WHERE report_id=?', (report_id,))
            for obs in observations:
                conn.execute('INSERT OR REPLACE INTO police_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', tuple(obs.values()))
            conn.execute(f'RELEASE SAVEPOINT police_{report_id.replace("-", "_")}')
        except Exception as exc:
            conn.execute(f'ROLLBACK TO SAVEPOINT police_{report_id.replace("-", "_")}')
            conn.execute(f'RELEASE SAVEPOINT police_{report_id.replace("-", "_")}')
            print('Police report import failed:', url, exc)
    conn.commit()
    docs = [dict(r) for r in conn.execute('SELECT report_id,title,report_year,report_type,source_url,local_path,retrieved_at,parse_status,summary FROM police_reports ORDER BY report_year DESC,title')]
    obs = [dict(r) for r in conn.execute('SELECT * FROM police_observations ORDER BY year DESC,subject_area,geography,metric LIMIT 20000')]
    subjects = {o['subject_area'] for o in obs}
    services = {o['police_service'] for o in obs if o['police_service']}
    years = {o['year'] for o in obs if o['year']}
    payload = {'generatedAt': now(), 'sourcePage': INDEX_URL, 'summary': {'reports': len(docs), 'observations': len(obs), 'subjects': len(subjects), 'services': len(services), 'years': len(years), 'needsReview': sum(1 for o in obs if o['verification_state'] == 'review')}, 'reports': docs, 'observations': obs}
    write_json_atomic(DATA / 'police-use-resources.json', payload)
    print(f'Police data: {len(docs)} reports, {len(obs)} observations')


if __name__ == '__main__':
    collect()
