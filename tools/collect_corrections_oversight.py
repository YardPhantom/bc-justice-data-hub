#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re,sqlite3,uuid
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'database'/'bc_justice.db'; DATA=ROOT/'data'; ARCH=ROOT/'imports'/'corrections-oversight'
UA='BCJusticeDataHub/0.2.6 (+private local research)'
SOURCES=[
 ('BC Investigation and Standards Office','https://www2.gov.bc.ca/gov/content/justice/criminal-justice/iso','government'),
 ('BC Ombudsperson corrections case summaries','https://bcombudsperson.ca/case-summaries/?query-0-category=corrections','ombudsperson'),
 ('Under Inspection report','https://bcombudsperson.ca/wp-content/uploads/2025/08/Special-Report-No-38-Under-Inspection-The-Hiatus-in-B.C.-Correctional-Centre-Inspections.pdf','ombudsperson'),
 ('Under Inspection update','https://bcombudsperson.ca/wp-content/uploads/2025/08/UnderInspection-Update_WEB.pdf','ombudsperson')]
def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def uid(*x): return str(uuid.uuid5(uuid.NAMESPACE_URL,'|'.join(map(str,x))))
def get(url):
 req=Request(url,headers={'User-Agent':UA})
 with urlopen(req,timeout=45) as r:return r.read(),r.headers.get_content_type()
def setup(c):
 c.executescript("""CREATE TABLE IF NOT EXISTS corrections_oversight_documents(document_id TEXT PRIMARY KEY,title TEXT,source_kind TEXT,document_type TEXT,published_date TEXT,facility TEXT,incident_type TEXT,source_url TEXT UNIQUE,local_path TEXT,sha256 TEXT,retrieved_at TEXT,parse_status TEXT,summary TEXT,raw_text TEXT);
 CREATE TABLE IF NOT EXISTS corrections_serious_incidents(incident_id TEXT PRIMARY KEY,document_id TEXT,facility TEXT,incident_type TEXT,incident_date TEXT,title TEXT,summary TEXT,source_url TEXT,verification_state TEXT DEFAULT 'review',created_at TEXT);""");c.commit()
def pdf_text(raw):
 try:
  from pypdf import PdfReader
  from io import BytesIO
  return '\n'.join((p.extract_text() or '') for p in PdfReader(BytesIO(raw)).pages),'parsed'
 except Exception as e:return '',f'failed: {e}'
def classify(text):
 t=text.lower(); typ='inspection/report'
 for label,pat in [('death in custody',r'death|died|fatal'),('serious assault',r'serious assault|assaulted'),('escape',r'escape'),('disturbance',r'disturbance|riot'),('use of force',r'use of force|excessive force'),('inspection',r'inspection|unannounced visit')]:
  if re.search(pat,t): typ=label;break
 facilities=['Alouette Correctional Centre for Women','Fraser Regional Correctional Centre','Kamloops Regional Correctional Centre','Nanaimo Correctional Centre','North Fraser Pretrial Centre','Okanagan Correctional Centre','Prince George Regional Correctional Centre','Surrey Pretrial Services Centre','Vancouver Island Regional Correctional Centre']
 fac=next((f for f in facilities if f.lower() in t),'')
 return typ,fac
def upsert(c,title,url,kind,raw,ctype):
 digest=hashlib.sha256(raw).hexdigest(); dtype='PDF' if 'pdf' in ctype or url.lower().endswith('.pdf') else 'HTML'; ext='.pdf' if dtype=='PDF' else '.html'; path=ARCH/f'{digest[:16]}{ext}'; path.write_bytes(raw)
 if dtype=='PDF': text,status=pdf_text(raw)
 else:
  from bs4 import BeautifulSoup
  text=' '.join(BeautifulSoup(raw,'html.parser').get_text(' ',strip=True).split());status='parsed'
 itype,facility=classify(title+' '+text[:12000]); did=uid(url); summary=' '.join(text.split())[:700]
 c.execute("""INSERT INTO corrections_oversight_documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_url) DO UPDATE SET title=excluded.title,local_path=excluded.local_path,sha256=excluded.sha256,retrieved_at=excluded.retrieved_at,parse_status=excluded.parse_status,summary=excluded.summary,raw_text=excluded.raw_text,facility=excluded.facility,incident_type=excluded.incident_type""",(did,title,kind,dtype,'',facility,itype,url,str(path.relative_to(ROOT)).replace('\\','/'),digest,now(),status,summary,text))
 if itype in ('death in custody','serious assault','escape','disturbance','use of force'):
  c.execute('INSERT OR REPLACE INTO corrections_serious_incidents VALUES(?,?,?,?,?,?,?,?,?,?)',(uid('incident',url),did,facility,itype,'',title,summary,url,'review',now()))
 return text
def collect():
 from bs4 import BeautifulSoup
 ARCH.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; setup(c); cases=[]
 for title,url,kind in SOURCES:
  try: raw,ctype=get(url)
  except Exception as e: print('Fetch failed',url,e); continue
  text=upsert(c,title,url,kind,raw,ctype)
  if 'case-summaries' in url:
   soup=BeautifulSoup(raw,'html.parser')
   for a in soup.find_all('a',href=True):
    href=urljoin(url,a['href']); label=' '.join(a.get_text(' ',strip=True).split())
    if '/case_summary/' in href: cases.append((label or href,href,'ombudsperson-case'))
 for title,url,kind in list(dict.fromkeys(cases))[:100]:
  try: raw,ctype=get(url); upsert(c,title,url,kind,raw,ctype)
  except Exception as e: print('Case fetch failed',url,e)
 c.commit(); docs=[dict(r) for r in c.execute('SELECT * FROM corrections_oversight_documents ORDER BY retrieved_at DESC')]; incidents=[dict(r) for r in c.execute('SELECT * FROM corrections_serious_incidents ORDER BY created_at DESC')]
 DATA.mkdir(exist_ok=True); (DATA/'corrections-oversight.json').write_text(json.dumps({'generatedAt':now(),'summary':{'documents':len(docs),'incidents':len(incidents),'facilities':len({r['facility'] for r in docs if r['facility']}),'needsReview':sum(1 for r in incidents if r['verification_state']=='review')},'documents':docs,'incidents':incidents},indent=2,ensure_ascii=False),encoding='utf-8')
 print(f'Corrections oversight: {len(docs)} documents, {len(incidents)} incident records')
if __name__=='__main__': collect()
