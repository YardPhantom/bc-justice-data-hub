from __future__ import annotations
import json, math, shutil
from pathlib import Path
from typing import Any, Iterable

def _serialise(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)

def write_json_atomic(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_suffix(target.suffix + '.bak')
    tmp = target.with_suffix(target.suffix + '.tmp')
    if target.exists():
        shutil.copyfile(target, backup)
    try:
        tmp.write_text(_serialise(payload), encoding='utf-8')
        tmp.replace(target)
    except Exception:
        if backup.exists() and not target.exists():
            shutil.copyfile(backup, target)
        raise

def write_json_compact_atomic(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_suffix(target.suffix + '.bak')
    tmp = target.with_suffix(target.suffix + '.tmp')
    if target.exists():
        shutil.copyfile(target, backup)
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':'), default=str), encoding='utf-8')
        tmp.replace(target)
    except Exception:
        if backup.exists() and not target.exists():
            shutil.copyfile(backup, target)
        raise

def write_paged_records(base_path: str | Path, key: str, records: list[dict], page_size: int = 5000, meta: dict | None = None) -> dict:
    base = Path(base_path)
    base.parent.mkdir(parents=True, exist_ok=True)
    meta = dict(meta or {})
    total = len(records)
    pages = max(1, math.ceil(total / page_size))
    stem = base.stem
    suffix = base.suffix
    for i in range(1, pages + 1):
        page_records = records[(i - 1) * page_size:i * page_size]
        payload = {**meta, 'page': i, 'pageSize': page_size, 'pageCount': pages, 'totalRecords': total, key: page_records}
        if i == 1:
            write_json_atomic(base, payload)
        write_json_atomic(base.with_name(f'{stem}-page-{i}{suffix}'), payload)
    return {'pageSize': page_size, 'pageCount': pages, 'totalRecords': total, 'firstPage': base.name}
