"""Configure the BC Justice SQLite database for concurrent readers and writers."""
from __future__ import annotations
import argparse, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_DB=ROOT/'database'/'bc_justice.db'

def configure(path:Path,timeout_seconds:int=60):
    if not path.exists():
        raise FileNotFoundError(f'Database not found: {path}')
    with sqlite3.connect(path,timeout=timeout_seconds) as connection:
        connection.execute(f'PRAGMA busy_timeout={max(1000,timeout_seconds*1000)}')
        mode=str(connection.execute('PRAGMA journal_mode=WAL').fetchone()[0] or '').casefold()
        if mode!='wal':
            raise RuntimeError(f'Unable to enable WAL mode; SQLite returned {mode or "unknown"}.')
        connection.execute('PRAGMA synchronous=NORMAL')
        connection.execute('PRAGMA wal_autocheckpoint=1000')
        connection.commit()
        return {
            'journalMode':mode,
            'busyTimeoutMs':max(1000,timeout_seconds*1000),
            'walAutoCheckpointPages':1000,
        }

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=DEFAULT_DB)
    parser.add_argument('--timeout',type=int,default=60)
    args=parser.parse_args()
    result=configure(args.database,max(1,args.timeout))
    print(f"SQLite concurrency ready: journal_mode={result['journalMode']}; busy_timeout={result['busyTimeoutMs']} ms; wal_autocheckpoint={result['walAutoCheckpointPages']} pages")

if __name__=='__main__':main()
