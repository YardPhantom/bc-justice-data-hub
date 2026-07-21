"""Small loopback helper that starts the BCJUS search API on demand."""
from __future__ import annotations
import json, os, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1]
STATUS_URL='http://127.0.0.1:8765/api/search/status'
HEARTBEAT_URL='http://127.0.0.1:8765/api/heartbeat'

def url_status(url,timeout=0.4):
    try:
        with urlopen(url,timeout=timeout) as response:return int(response.status)
    except HTTPError as exc:
        return int(exc.code)
    except Exception:
        return 0

def api_reachable(timeout=0.4):
    return url_status(HEARTBEAT_URL,timeout)==200

def api_ready(timeout=0.4):
    return url_status(STATUS_URL,timeout)==200

def start_api():
    if api_reachable():return True
    reports=ROOT/'reports';reports.mkdir(exist_ok=True)
    pythonw=Path(sys.executable).with_name('pythonw.exe');exe=str(pythonw if pythonw.exists() else Path(sys.executable))
    flags=(getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'DETACHED_PROCESS',0)) if os.name=='nt' else 0
    out=open(reports/'search-api.log','a',encoding='utf-8');err=open(reports/'search-api-error.log','a',encoding='utf-8')
    proc=subprocess.Popen([exe,str(ROOT/'tools'/'search_api.py'),'--idle-timeout','300'],cwd=ROOT,stdout=out,stderr=err,creationflags=flags,close_fds=True)
    (reports/'search-api.pid').write_text(str(proc.pid),encoding='ascii')
    for _ in range(30):
        if api_reachable():return True
        time.sleep(0.1)
    return False

class Handler(BaseHTTPRequestHandler):
    server_version='BCJUSSearchSupervisor/0.20.2'
    def reply(self,payload,code=200):
        raw=json.dumps(payload,separators=(',',':')).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.send_header('Access-Control-Allow-Origin','*');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
    def do_OPTIONS(self):
        self.send_response(204);self.send_header('Access-Control-Allow-Origin','*');self.send_header('Access-Control-Allow-Methods','GET,OPTIONS');self.end_headers()
    def do_GET(self):
        if self.path.startswith('/wake'):
            running=start_api();ready=api_ready() if running else False
            return self.reply({'ok':running,'api':'http://127.0.0.1:8765','apiRunning':running,'apiReady':ready,'idleTimeoutSeconds':300},200 if running else 503)
        if self.path.startswith('/status'):
            running=api_reachable();return self.reply({'ok':True,'apiRunning':running,'apiReady':api_ready() if running else False})
        return self.reply({'error':'Not found'},404)
    def log_message(self,*_):pass

if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',8764),Handler).serve_forever()
