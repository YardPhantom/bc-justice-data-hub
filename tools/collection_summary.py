#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'database' / 'bc_justice.db'
OUT = ROOT / 'data' / 'collection-summary.json'


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def status_message(status: str, code: int) -> str:
    messages = {
        'collected': 'Collection is complete. Automatic post-processing is next.',
        'postprocessing': 'Collection is complete. Automatic post-processing is running.',
        'success': 'All collection and post-processing completed successfully.',
        'failed': 'Collection completed with errors. Review recent failures.',
        'postprocess-failed': 'Collection completed, but automatic post-processing failed.',
    }
    return messages.get(status, 'Collection completed successfully.' if code == 0 else 'Collection completed with errors. Review recent failures.')


def main():
    status = sys.argv[1] if len(sys.argv) > 1 else 'unknown'
    code = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    payload = {
        'generatedAt': now(),
        'status': status,
        'exitCode': code,
        'failedImports': 0,
        'openReviews': 0,
        'recentFailures': [],
        'message': status_message(status, code),
    }
    if DB.exists():
        c = sqlite3.connect(DB, timeout=60)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA busy_timeout=60000')
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'catalogue_resources' in names:
            payload['failedImports'] = c.execute("SELECT COUNT(*) FROM catalogue_resources WHERE import_state='failed'").fetchone()[0]
            payload['recentFailures'] = [dict(r) for r in c.execute("SELECT dataset_id,resource_id,name,import_error FROM catalogue_resources WHERE import_state='failed' ORDER BY imported_at DESC LIMIT 20")]
        if 'review_queue' in names:
            payload['openReviews'] = c.execute("SELECT COUNT(*) FROM review_queue WHERE status='open'").fetchone()[0]
        c.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(OUT)
    print(payload['message'], f"Failed imports: {payload['failedImports']}. Open reviews: {payload['openReviews']}.")
    return code


if __name__ == '__main__':
    raise SystemExit(main())
