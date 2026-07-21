#!/usr/bin/env python3
from __future__ import annotations
import importlib.util,json,sqlite3,tempfile
from contextlib import closing
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
pi=load('person_identity',ROOT/'tools'/'person_identity.py');af=load('advanced_features',ROOT/'tools'/'advanced_features.py')
def check(ok,msg):
 if not ok:raise AssertionError(msg)
def main():
 with tempfile.TemporaryDirectory() as td:
  db=Path(td)/'test.db';data=Path(td)/'data';data.mkdir();pi.DATA=data;af.DATA=data
  with closing(sqlite3.connect(db)) as c:
   c.row_factory=sqlite3.Row
   c.executescript('''
   CREATE TABLE people(person_id TEXT PRIMARY KEY,display_name TEXT,normalized_name TEXT,date_of_birth TEXT,identity_confidence REAL,review_required INTEGER,created_at TEXT,updated_at TEXT,birth_year TEXT,sex TEXT,identity_status TEXT,identity_notes TEXT);
   CREATE TABLE cases(case_id TEXT PRIMARY KEY,case_title TEXT,court_file_number TEXT,citation TEXT,opened_date TEXT,outcome_date TEXT,closed_date TEXT,offence_date TEXT,courthouse_slug TEXT,case_type TEXT,legal_status TEXT,final_outcome TEXT,verification_state TEXT,source_url TEXT,related_case_id TEXT);
   CREATE TABLE case_people(case_id TEXT,person_id TEXT,role TEXT);
   CREATE TABLE charges(charge_id TEXT PRIMARY KEY,case_id TEXT,offence_text TEXT,statute TEXT,section TEXT,disposition TEXT,offence_group TEXT,event_key TEXT,offence_date TEXT);
   CREATE TABLE outcomes(outcome_id TEXT PRIMARY KEY,case_id TEXT,outcome_type TEXT,outcome_date TEXT,sentence_summary TEXT,verified INTEGER);
   CREATE TABLE review_queue(review_id TEXT PRIMARY KEY,entity_type TEXT,entity_id TEXT,reason TEXT,severity TEXT,status TEXT,created_at TEXT);
   ''')
   pi.setup(c);af.setup(c);now=pi.now();c.execute("INSERT INTO people VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",('p1','Alex Example','alex example',None,.95,0,now,now,'1980',None,'verified',None));c.execute("INSERT INTO people VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",('p2','Alex Example','alex example',None,.75,1,now,now,'1981',None,'review',None))
   cases=[('c1','R v Example','111','2020 BCPC 1','2020-01-01','2020-06-01','2020-06-01','2020-01-01','victoria','trial','convicted','convicted','verified','u1',None),('c2','R v Example sentencing','111','2020 BCPC 1','2020-01-01','2020-08-01','2020-08-01','2020-01-01','victoria','sentencing','convicted','convicted','verified','u2','c1'),('c3','R v Example','222','2024 BCPC 2','2024-02-01','2024-05-01','2024-05-01','2024-02-01','nanaimo','trial','convicted','convicted','verified','u3',None)]
   c.executemany('INSERT INTO cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',cases)
   c.executemany('INSERT INTO case_people VALUES(?,?,?)',[(x[0],'p1','accused') for x in cases])
   c.executemany('INSERT INTO charges(charge_id,case_id,offence_text,statute,section,disposition,offence_group,event_key,offence_date) VALUES(?,?,?,?,?,?,?,?,?)',[('ch1','c1','Theft','Criminal Code','334','convicted','property','occ-1','2020-01-01'),('ch2','c2','Theft','Criminal Code','334','convicted','property','occ-1','2020-01-01'),('ch3','c3','Breach','Criminal Code','145','convicted','administration of justice','occ-2','2024-02-01')])
   c.executemany('INSERT INTO outcomes VALUES(?,?,?,?,?,?)',[('o1','c1','convicted','2020-06-01','30 days custody',1),('o2','c2','convicted','2020-08-01','',1),('o3','c3','convicted','2024-05-01','probation',1)])
   c.commit();af.duplicate_people(c);count=pi.events(c);check(count==2,'linked sentencing must not inflate event count')
   e=[dict(x) for x in c.execute('SELECT * FROM conviction_events ORDER BY offence_date')];check(len(json.loads(e[0]['linked_case_ids']))==2,'linked cases recorded');check(e[0]['offence_date']=='2020-01-01' and e[1]['offence_date']=='2024-02-01','offence-date separation')
   c.execute("INSERT INTO judgment_prior_history VALUES(?,?,?,?,?,?,?,?,?,?,?)",('h1','j1','p1','The judge described a lengthy criminal record and 6 prior convictions.',6,'2000','2019','[]',0,.8,now));c.commit()
   af.repeat_offenders(c);payload=json.loads((data/'repeat-offenders.json').read_text());r=payload['records'][0]
   check(r['linked_proceeding_count']==1,'linked proceeding count');check(r['conviction_sequence'][0]['court_file_number']=='111','timeline court file');check(r['conviction_sequence'][0]['source_url']=='u1','timeline source link');check(r['historical_coverage'] in ('partial','recent years only'),'coverage indicator');check(r['missing_history_alert'],'missing-history alert');check(r['max_gap_years']==4,'conviction gap');check(r['has_custodial_sentence'],'custodial sentence filter field');check(r['identity_evidence'],'identity evidence');check(r['duplicate_candidates'],'duplicate warning candidates');check(r['conviction_sequence'][0]['sentence_summary']=='30 days custody','sentence summary exported')
 print('Repeat-offender regression tests passed.')
if __name__=='__main__':main()
