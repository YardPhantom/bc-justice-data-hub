#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, hashlib, io, json, os, re, sqlite3, urllib.error, urllib.request, zipfile
from datetime import datetime, timezone
from pathlib import Path

from export_utils import write_json_compact_atomic

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'database' / 'bc_justice.db'
OUT = ROOT / 'data' / 'statcan-crime.json'
RAW = ROOT / 'imports' / 'statcan'
CHECK_INTERVAL_DAYS = {'35100184': 30}
DEFER_HEAVY_TABLES = {'35100184'}
TABLES = {
    '35100063': {'title': 'Crime Severity Index and weighted clearance rates, police services in British Columbia', 'scope': 'police-service', 'url': 'https://www150.statcan.gc.ca/n1/en/tbl/csv/35100063-eng.zip'},
    '35100184': {'title': 'Incident-based crime statistics, by detailed violations, police services in British Columbia', 'scope': 'police-service', 'url': 'https://www150.statcan.gc.ca/n1/en/tbl/csv/35100184-eng.zip'},
    '35100026': {'title': 'Crime Severity Index and weighted clearance rates, Canada, provinces, territories and CMAs', 'scope': 'province-cma', 'url': 'https://www150.statcan.gc.ca/n1/en/tbl/csv/35100026-eng.zip'},
}


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def norm(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def num(value):
    try:
        return float(str(value).replace(',', '').strip())
    except Exception:
        return None


def pick(row, *needles):
    for key, value in row.items():
        lowered = str(key or '').lower()
        if any(needle in lowered for needle in needles):
            return norm(value)
    return ''


def schema(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS statcan_sources(table_id TEXT PRIMARY KEY,title TEXT,source_url TEXT,scope TEXT,last_checked TEXT,last_changed TEXT,sha256 TEXT,latest_year INTEGER,status TEXT,error TEXT,remote_etag TEXT,remote_last_modified TEXT,remote_size INTEGER);
    CREATE TABLE IF NOT EXISTS statcan_crime_statistics(id INTEGER PRIMARY KEY AUTOINCREMENT,table_id TEXT,ref_date TEXT,geography TEXT,police_service TEXT,metric TEXT,violation TEXT,statistics TEXT,value REAL,unit TEXT,scalar_factor TEXT,status TEXT,source_url TEXT,raw_json TEXT,UNIQUE(table_id,ref_date,geography,police_service,metric,violation,statistics));
    ''')


def ensure_source_columns(c):
    cols = {r[1] for r in c.execute('PRAGMA table_info(statcan_sources)')}
    for name, sql_type in (('remote_etag', 'TEXT'), ('remote_last_modified', 'TEXT'), ('remote_size', 'INTEGER')):
        if name not in cols:
            c.execute(f'ALTER TABLE statcan_sources ADD COLUMN {name} {sql_type}')


def recently_checked(old, table_id):
    if not old or not old['last_checked']:
        return False
    days = CHECK_INTERVAL_DAYS.get(table_id, 0)
    if not days:
        return False
    try:
        checked = datetime.fromisoformat(str(old['last_checked']).replace('Z', '+00:00'))
        return (datetime.now(timezone.utc) - checked).total_seconds() < days * 86400
    except Exception:
        return False


def remote_metadata(meta):
    req = urllib.request.Request(meta['url'], method='HEAD', headers={'User-Agent': 'BC Justice Data Hub/0.8.4 private research'})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            headers = response.headers
            return {'etag': norm(headers.get('ETag')), 'last_modified': norm(headers.get('Last-Modified')), 'size': int(headers.get('Content-Length') or 0)}
    except Exception:
        return {'etag': '', 'last_modified': '', 'size': 0}


def same_remote(old, remote):
    if not old:
        return False
    old_etag = norm(old['remote_etag'])
    old_lm = norm(old['remote_last_modified'])
    old_size = int(old['remote_size'] or 0)
    if remote['etag'] and old_etag:
        return remote['etag'] == old_etag
    if remote['last_modified'] and old_lm and remote['size'] and old_size:
        return remote['last_modified'] == old_lm and remote['size'] == old_size
    return False


def human_bytes(value):
    size = float(value or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.1f} {unit}' if unit != 'B' else f'{int(size)} B'
        size /= 1024
    return f'{size:.1f} GB'


def progress_bar(done, total, width=20):
    if not total:
        return '[' + ('#' * min(width, max(1, int(done / (1024 * 1024)))))[:width].ljust(width, '-') + ']'
    ratio = min(1.0, done / total)
    filled = int(width * ratio)
    return '[' + ('#' * filled) + ('-' * (width - filled)) + ']'


def cache_paths(table_id):
    archive = RAW / f'{table_id}-eng.zip'
    sidecar = RAW / f'{table_id}-eng.cache.json'
    return archive, sidecar


def read_cache_meta(table_id):
    _, sidecar = cache_paths(table_id)
    try:
        payload = json.loads(sidecar.read_text(encoding='utf-8'))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def valid_cached_archive(table_id, expected_sha=''):
    archive, _ = cache_paths(table_id)
    if not archive.exists() or archive.stat().st_size < 1024:
        return False
    try:
        with zipfile.ZipFile(archive) as zf:
            if not csv_info(zf):
                return False
    except Exception:
        return False
    if expected_sha:
        digest = hashlib.sha256()
        with archive.open('rb') as handle:
            for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest() == expected_sha
    return True


def write_cache_meta(table_id, *, digest, remote, size):
    _, sidecar = cache_paths(table_id)
    payload = {
        'tableId': table_id,
        'sha256': digest,
        'etag': remote.get('etag', ''),
        'lastModified': remote.get('last_modified', ''),
        'remoteSize': int(remote.get('size') or 0),
        'archiveSize': int(size or 0),
        'cachedAt': now(),
    }
    temp = sidecar.with_suffix(sidecar.suffix + '.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, sidecar)


def download(meta, table_id, old=None):
    archive_path, _ = cache_paths(table_id)
    partial_path = archive_path.with_suffix(archive_path.suffix + '.part')
    headers = {'User-Agent': 'BC Justice Data Hub/0.10.4 private research'}
    if old:
        if norm(old['remote_etag']):
            headers['If-None-Match'] = norm(old['remote_etag'])
        if norm(old['remote_last_modified']):
            headers['If-Modified-Since'] = norm(old['remote_last_modified'])
    req = urllib.request.Request(meta['url'], headers=headers)
    try:
        print(f'Statistics Canada {table_id}: [2/7] connecting to download...', flush=True)
        with urllib.request.urlopen(req, timeout=180) as response:
            total = int(response.headers.get('Content-Length') or 0)
            print(f'Statistics Canada {table_id}: [3/7] downloading archive to persistent cache'
                  + (f' ({human_bytes(total)})...' if total else '...'), flush=True)
            downloaded = 0
            last_report = -1
            digest = hashlib.sha256()
            partial_path.unlink(missing_ok=True)
            with partial_path.open('wb') as output:
                while True:
                    chunk = response.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    percent = int(downloaded * 100 / total) if total else downloaded // (5 * 1024 * 1024)
                    if percent != last_report and (not total or percent >= last_report + 2):
                        last_report = percent
                        suffix = f'{int(downloaded * 100 / total)}%' if total else human_bytes(downloaded)
                        print(f'\rStatistics Canada {table_id}: {progress_bar(downloaded, total)} {suffix} | {human_bytes(downloaded)} downloaded', end='', flush=True)
                output.flush()
                os.fsync(output.fileno())
            if total:
                print(f'\rStatistics Canada {table_id}: {progress_bar(total, total)} 100% | {human_bytes(downloaded)} downloaded', flush=True)
            else:
                print('', flush=True)
            os.replace(partial_path, archive_path)
            print(f'Statistics Canada {table_id}: download cached ({human_bytes(downloaded)}).', flush=True)
            response_remote = {
                'etag': norm(response.headers.get('ETag')),
                'last_modified': norm(response.headers.get('Last-Modified')),
                'size': int(response.headers.get('Content-Length') or downloaded),
            }
            return archive_path, digest.hexdigest(), response_remote, False
    except urllib.error.HTTPError as exc:
        partial_path.unlink(missing_ok=True)
        if exc.code == 304:
            return archive_path, '', {}, True
        raise
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise


class CountingReader(io.RawIOBase):
    def __init__(self, stream):
        self.stream = stream
        self.bytes_read = 0

    def readable(self):
        return True

    def readinto(self, buffer):
        data = self.stream.read(len(buffer))
        if not data:
            return 0
        size = len(data)
        buffer[:size] = data
        self.bytes_read += size
        return size

    def close(self):
        try:
            self.stream.close()
        finally:
            super().close()


def csv_info(zf):
    infos = [info for info in zf.infolist() if info.filename.lower().endswith('.csv') and 'metadata' not in info.filename.lower()]
    if not infos:
        raise RuntimeError('No CSV found in Statistics Canada archive')
    return max(infos, key=lambda info: info.file_size)

def row_record(table_id, row, meta):
    ref = pick(row, 'ref_date', 'reference period')
    geo = pick(row, 'geo', 'geography')
    police_service = pick(row, 'police service', 'policing district', 'police services')
    metric = pick(row, 'crime severity index', 'weighted clearance', 'characteristics', 'index type')
    violation = pick(row, 'violations', 'violation')
    statistics = pick(row, 'statistics')
    unit = pick(row, 'uom', 'unit of measure')
    scalar = pick(row, 'scalar factor')
    status = pick(row, 'status')
    value = num(row.get('VALUE'))
    if value is None:
        for key, raw in row.items():
            if str(key or '').upper() == 'VALUE':
                value = num(raw)
                break
    if not metric:
        metric = violation or statistics
    return (table_id, ref, geo, police_service, metric, violation, statistics, value, unit, scalar, status, meta['url'], json.dumps(row, ensure_ascii=False))


def import_table(c, table_id, meta, old, checked, force=False, quick=False, refresh_large=False):
    existing_count = c.execute('SELECT COUNT(*) FROM statcan_crime_statistics WHERE table_id=?', (table_id,)).fetchone()[0]
    if existing_count and recently_checked(old, table_id) and not force:
        return {'changed': False, 'rows': existing_count, 'latestYear': old['latest_year'] or 0, 'skipped': True}
    remote = remote_metadata(meta)
    if existing_count and same_remote(old, remote) and not force:
        c.execute('UPDATE statcan_sources SET last_checked=?,status=?,error=? WHERE table_id=?', (checked, 'ok', '', table_id))
        return {'changed': False, 'rows': existing_count, 'latestYear': old['latest_year'] or 0, 'skipped': True}
    if quick and existing_count and not force and not any(remote.values()):
        print(f'Statistics Canada {table_id}: quick check could not confirm a change; keeping existing {existing_count:,} records.', flush=True)
        c.execute('UPDATE statcan_sources SET last_checked=?,status=?,error=? WHERE table_id=?', (checked, 'ok', '', table_id))
        return {'changed': False, 'rows': existing_count, 'latestYear': old['latest_year'] or 0, 'skipped': True}
    if table_id in DEFER_HEAVY_TABLES and existing_count and not force and not refresh_large:
        print(
            f'Statistics Canada {table_id}: source update detected, but the full 5.8 GB / 20M+ row rebuild is deferred during normal Collect New.',
            flush=True,
        )
        print(
            f'Statistics Canada {table_id}: keeping the last verified {existing_count:,}-record snapshot. Run "py -u tools\\collect_statcan_crime.py --refresh-large" when a full annual refresh is wanted.',
            flush=True,
        )
        c.execute(
            'UPDATE statcan_sources SET last_checked=?,status=?,error=?,remote_etag=?,remote_last_modified=?,remote_size=? WHERE table_id=?',
            (checked, 'update_available', 'Heavy refresh deferred; existing verified snapshot retained.', remote['etag'], remote['last_modified'], remote['size'], table_id),
        )
        return {'changed': False, 'rows': existing_count, 'latestYear': old['latest_year'] or 0, 'skipped': True}
    archive_path, _ = cache_paths(table_id)
    cached_meta = read_cache_meta(table_id)
    expected_sha = norm((old['sha256'] if old else '') or cached_meta.get('sha256'))
    cache_valid = valid_cached_archive(table_id, expected_sha)

    # A populated database plus a verified cached archive is enough to avoid a
    # multi-gigabyte transfer when StatCan does not return reliable HEAD metadata.
    if existing_count and cache_valid and not force and not any(remote.values()):
        print(f'Statistics Canada {table_id}: remote metadata unavailable; using verified cached archive and {existing_count:,} existing records.', flush=True)
        c.execute('UPDATE statcan_sources SET last_checked=?,status=?,error=? WHERE table_id=?', (checked, 'ok', '', table_id))
        return {'changed': False, 'rows': existing_count, 'latestYear': old['latest_year'] or 0, 'skipped': True}

    print(f'Statistics Canada {table_id}: [1/7] updated source detected.', flush=True)
    archive_path, digest, response_remote, not_modified = download(meta, table_id, old)
    if not_modified and existing_count:
        c.execute('UPDATE statcan_sources SET last_checked=?,status=?,error=? WHERE table_id=?', (checked, 'ok', '', table_id))
        return {'changed': False, 'rows': existing_count, 'latestYear': old['latest_year'] or 0, 'skipped': True}
    if response_remote:
        remote = response_remote
    changed = not old or old['sha256'] != digest
    if not changed and existing_count:
        write_cache_meta(table_id, digest=digest, remote=remote, size=archive_path.stat().st_size)
        c.execute('UPDATE statcan_sources SET last_checked=?,status=?,error=?,remote_etag=?,remote_last_modified=?,remote_size=? WHERE table_id=?', (checked, 'ok', '', remote['etag'], remote['last_modified'], remote['size'], table_id))
        print(f'Statistics Canada {table_id}: downloaded content matches cache; database reimport skipped.', flush=True)
        return {'changed': False, 'rows': existing_count, 'latestYear': old['latest_year'] or 0, 'skipped': True}

    print(f'Statistics Canada {table_id}: [4/7] validating cached archive...', flush=True)
    with zipfile.ZipFile(archive_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith('.csv') and 'metadata' not in n.lower()]
        if not names:
            raise RuntimeError('No CSV found in Statistics Canada archive')
    print(f'Statistics Canada {table_id}: archive validation complete.', flush=True)
    latest = 0
    count = 0
    processed = 0
    insert_sql = '''INSERT OR IGNORE INTO statcan_crime_statistics(table_id,ref_date,geography,police_service,metric,violation,statistics,value,unit,scalar_factor,status,source_url,raw_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)'''
    c.execute(f'SAVEPOINT statcan_{table_id}')
    try:
        c.execute('DELETE FROM statcan_crime_statistics WHERE table_id=?', (table_id,))
        with zipfile.ZipFile(archive_path) as zf:
            info = csv_info(zf)
            print(f'Statistics Canada {table_id}: [5/7] streaming {human_bytes(info.file_size)} CSV directly from archive...', flush=True)
            counter = CountingReader(zf.open(info, 'r'))
            buffered = io.BufferedReader(counter, buffer_size=4 * 1024 * 1024)
            text_stream = io.TextIOWrapper(buffered, encoding='utf-8-sig', errors='replace', newline='')
            reader = csv.DictReader(text_stream)
            print(f'Statistics Canada {table_id}: [6/7] importing CSV rows...', flush=True)
            batch = []
            for row in reader:
                processed += 1
                record = row_record(table_id, row, meta)
                geo_hay = (record[2] + ' ' + record[3]).lower()
                if table_id == '35100026' and not any(x in geo_hay for x in ('british columbia', 'vancouver', 'victoria', 'kelowna', 'abbotsford', 'nanaimo', 'kamloops', 'chilliwack')):
                    continue
                try:
                    latest = max(latest, int(str(record[1])[:4]))
                except Exception:
                    pass
                batch.append(record)
                count += 1
                if len(batch) >= 2000:
                    c.executemany(insert_sql, batch)
                    batch.clear()
                if processed == 1 or processed % 25000 == 0:
                    pct = int(min(100, counter.bytes_read * 100 / info.file_size)) if info.file_size else 0
                    print(f'\rStatistics Canada {table_id}: {progress_bar(counter.bytes_read, info.file_size)} {pct}% | {human_bytes(counter.bytes_read)} read | {processed:,} rows | {count:,} records kept', end='', flush=True)
            if batch:
                c.executemany(insert_sql, batch)
            if processed:
                print(f'\rStatistics Canada {table_id}: {progress_bar(info.file_size, info.file_size)} 100% | {human_bytes(counter.bytes_read)} read | {processed:,} rows | {count:,} records kept', flush=True)
        if not count and existing_count:
            raise RuntimeError('replacement import produced 0 records; kept prior snapshot')
        changed_at = checked if changed else (old['last_changed'] if old else checked)
        c.execute('''INSERT INTO statcan_sources(table_id,title,source_url,scope,last_checked,last_changed,sha256,latest_year,status,error,remote_etag,remote_last_modified,remote_size)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(table_id) DO UPDATE SET
                       title=excluded.title,source_url=excluded.source_url,scope=excluded.scope,
                       last_checked=excluded.last_checked,last_changed=excluded.last_changed,
                       sha256=excluded.sha256,latest_year=excluded.latest_year,status=excluded.status,
                       error=excluded.error,remote_etag=excluded.remote_etag,
                       remote_last_modified=excluded.remote_last_modified,remote_size=excluded.remote_size''',
                  (table_id, meta['title'], meta['url'], meta['scope'], checked, changed_at, digest, latest, 'ok', '', remote['etag'], remote['last_modified'], remote['size']))
        c.execute(f'RELEASE SAVEPOINT statcan_{table_id}')
        print(f'Statistics Canada {table_id}: [7/7] database import committed ({count:,} records).', flush=True)
    except Exception:
        c.execute(f'ROLLBACK TO SAVEPOINT statcan_{table_id}')
        c.execute(f'RELEASE SAVEPOINT statcan_{table_id}')
        raise
    write_cache_meta(table_id, digest=digest, remote=remote, size=archive_path.stat().st_size)
    return {'changed': changed, 'rows': count, 'latestYear': latest, 'skipped': False}


def main():
    parser = argparse.ArgumentParser(description='Collect Statistics Canada crime tables incrementally.')
    parser.add_argument('--force', action='store_true', help='Redownload and reimport even when remote metadata is unchanged.')
    parser.add_argument('--quick', action='store_true', help='Perform metadata checks and avoid uncertain large downloads.')
    parser.add_argument('--refresh-large', action='store_true', help='Allow the very large 35100184 annual archive to download and rebuild.')
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    schema(conn)
    c = conn.cursor()
    ensure_source_columns(c)
    changes = []
    errors = []
    for table_id, meta in TABLES.items():
        checked = now()
        print(f'Statistics Canada {table_id}: checking source...', flush=True)
        try:
            old = c.execute('SELECT * FROM statcan_sources WHERE table_id=?', (table_id,)).fetchone()
            result = import_table(c, table_id, meta, old, checked, force=args.force, quick=args.quick, refresh_large=args.refresh_large)
            changes.append({'tableId': table_id, 'title': meta['title'], 'changed': result['changed'], 'rows': result['rows'], 'latestYear': result['latestYear'], 'sourceUrl': meta['url']})
            if result['skipped']:
                print(f"Statistics Canada {table_id}: kept {result['rows']} records.", flush=True)
            else:
                print(f"Statistics Canada {table_id}: imported {result['rows']} records.", flush=True)
        except Exception as exc:
            errors.append({'tableId': table_id, 'title': meta['title'], 'error': str(exc)})
            c.execute('''INSERT INTO statcan_sources(table_id,title,source_url,scope,last_checked,status,error)
                         VALUES(?,?,?,?,?,?,?)
                         ON CONFLICT(table_id) DO UPDATE SET last_checked=excluded.last_checked,status=excluded.status,error=excluded.error''',
                      (table_id, meta['title'], meta['url'], meta['scope'], checked, 'failed', str(exc)))
    conn.commit()
    rows = [dict(r) for r in conn.execute('SELECT table_id,ref_date,geography,police_service,metric,violation,statistics,value,unit,scalar_factor,status,source_url FROM statcan_crime_statistics ORDER BY ref_date DESC,geography,metric LIMIT 75000')]
    sources = [dict(r) for r in conn.execute('SELECT * FROM statcan_sources ORDER BY table_id')]
    years = sorted({r['ref_date'] for r in rows if r['ref_date']}, reverse=True)
    payload = {
        'generatedAt': now(),
        'sourceAuthority': 'Statistics Canada',
        'sourceLevel': 'Federal',
        'licence': 'Open Government Licence - Canada',
        'notice': 'Police-reported statistics. CSI measures volume and severity and is not, by itself, an overall safety measure.',
        'summary': {
            'records': len(rows),
            'tables': len(sources),
            'geographies': len({r['geography'] or r['police_service'] for r in rows}),
            'years': len(years),
            'failedSources': len(errors),
        },
        'changes': changes,
        'errors': errors,
        'sources': sources,
        'records': rows,
    }
    write_json_compact_atomic(OUT, payload)
    print(f"Statistics Canada crime: {len(rows)} records, {len(errors)} source errors.")
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
