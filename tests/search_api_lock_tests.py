import importlib.util, json, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('search_api_lock',ROOT/'tools'/'search_api.py')
api=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(api)


def test_wal_read_only_connection_reads_during_writer_transaction(tmp_path):
    db=tmp_path/'justice.db'
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE sample(id INTEGER PRIMARY KEY,value TEXT)')
        connection.execute("INSERT INTO sample(value) VALUES('before')")
    old_db,old_mode=api.DB,api.WAL_MODE
    try:
        api.DB=db
        assert api.configure_database_concurrency() is True
        writer=sqlite3.connect(db,timeout=1)
        writer.execute('BEGIN IMMEDIATE')
        writer.execute("UPDATE sample SET value='during' WHERE id=1")
        with api.connect(read_only=True,timeout=1) as reader:
            assert reader.execute('PRAGMA query_only').fetchone()[0]==1
            assert reader.execute('SELECT value FROM sample WHERE id=1').fetchone()[0]=='before'
        writer.rollback();writer.close()
    finally:
        api.DB,api.WAL_MODE=old_db,old_mode


def test_read_only_appearance_cache_never_attempts_schema_writes(tmp_path):
    db=tmp_path/'appearance.db'
    with sqlite3.connect(db) as connection:
        connection.executescript(api.APPEARANCE_CACHE_SCHEMA)
        payload={'appearance_id':'a1','participant_name':'DOE, JANE'}
        connection.execute('INSERT INTO appearance_search_records VALUES(?,?,?,?,?,?,?,?,?,?)',('a1','DOE, JANE','doe jane','','','','2026-07-21','Charge Not Available',json.dumps(payload),'2026-07-21'))
    old_db=api.DB
    try:
        api.DB=db
        with api.connect(read_only=True,timeout=1) as reader:
            assert api.ensure_appearance_cache(reader)==1
    finally:
        api.DB=old_db


def test_lock_errors_are_retryable_503s_and_heartbeat_is_database_independent():
    assert api.database_busy(sqlite3.OperationalError('database is locked'))
    assert api.database_busy(sqlite3.OperationalError('database schema is locked'))
    assert not api.database_busy(sqlite3.OperationalError('no such table'))
    source=(ROOT/'tools'/'search_api.py').read_text(encoding='utf-8')
    assert "'code':'database_busy'" in source
    assert "503,{'Retry-After':'2'}" in source
    heartbeat=source.index("if parsed.path=='/api/heartbeat'")
    readonly=source.index('with connect(read_only=True) as c:',heartbeat)
    assert heartbeat<readonly


def test_supervisor_distinguishes_running_from_database_ready():
    source=(ROOT/'tools'/'search_supervisor.py').read_text(encoding='utf-8')
    assert 'HEARTBEAT_URL' in source
    assert "'apiRunning':running" in source
    assert "'apiReady':ready" in source
    assert 'if api_reachable():return True' in source


def test_locked_database_returns_http_503(tmp_path):
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.error import HTTPError
    from urllib.request import urlopen
    db=tmp_path/'locked.db'
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE search_records(record_id TEXT)')
    old_db,old_connect=api.DB,api.connect
    server=None;writer=None
    try:
        api.DB=db
        api.connect=lambda read_only=False,timeout=None: old_connect(read_only=read_only,timeout=0.1)
        writer=sqlite3.connect(db,timeout=1)
        writer.execute('PRAGMA journal_mode=DELETE')
        writer.execute('BEGIN EXCLUSIVE')
        server=ThreadingHTTPServer(('127.0.0.1',0),api.Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        url=f'http://127.0.0.1:{server.server_address[1]}/api/search/status'
        try:
            urlopen(url,timeout=2)
            assert False,'expected HTTP 503'
        except HTTPError as exc:
            body=json.loads(exc.read().decode('utf-8'))
            assert exc.code==503
            assert exc.headers.get('Retry-After')=='2'
            assert body['code']=='database_busy' and body['retryable'] is True
    finally:
        if server:
            server.shutdown();server.server_close()
        if writer:
            writer.rollback();writer.close()
        api.DB,api.connect=old_db,old_connect
