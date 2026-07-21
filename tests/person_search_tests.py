#!/usr/bin/env python3
from __future__ import annotations
import importlib.util,sys,tempfile,sqlite3
from contextlib import closing
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('person_identity',ROOT/'tools'/'person_identity.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def check(ok,msg):
 if not ok: raise AssertionError(msg)
def main():
 check(m.soundex('Stephen')==m.soundex('Steven'),'phonetic given names')
 check(m.soundex('MacDonald')==m.soundex('McDonald'),'phonetic surnames')
 check(m.levenshtein('jon smith','john smith',3)<=2,'minor typo tolerance')
 check('John R. Smith' in m.expanded_name_variants('John Robert Smith'),'initial variant')
 with tempfile.TemporaryDirectory() as td:
  db=Path(td)/'person-search-test.db'
  with closing(sqlite3.connect(db)) as c:
   c.row_factory=sqlite3.Row
   c.executescript("CREATE TABLE people(person_id TEXT PRIMARY KEY,display_name TEXT,normalized_name TEXT,date_of_birth TEXT,identity_confidence REAL,review_required INTEGER,created_at TEXT,updated_at TEXT,birth_year TEXT,sex TEXT,identity_status TEXT,identity_notes TEXT); CREATE TABLE published_judgments(judgment_id TEXT PRIMARY KEY,decision_date TEXT);"+m.SCHEMA)
   now=m.now(); rows=[('a','Stephen MacDonald','stephen macdonald','1980'),('b','Steven McDonald','steven mcdonald','1980'),('c','Steven McDonald','steven mcdonald','1998'),('d','Stephen McDonald','stephen mcdonald','1980')]
   for pid,name,norm,birth in rows:c.execute('INSERT INTO people(person_id,display_name,normalized_name,birth_year,identity_confidence,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(pid,name,norm,birth,.3,now,now))
   c.execute("INSERT INTO person_identity_signals VALUES(?,?,?,?,?,?,?,?,?)",('s1','a','birth_year','1980','person','a',.25,1,now));c.execute("INSERT INTO person_identity_signals VALUES(?,?,?,?,?,?,?,?,?)",('s2','b','birth_year','1980','person','b',.25,1,now));c.execute("INSERT INTO person_identity_signals VALUES(?,?,?,?,?,?,?,?,?)",('s3','c','birth_year','1998','person','c',.25,1,now));
   c.execute("INSERT INTO person_identity_signals VALUES(?,?,?,?,?,?,?,?,?)",('l1','a','case_location','nanaimo','case','ca',.08,0,now));c.execute("INSERT INTO person_identity_signals VALUES(?,?,?,?,?,?,?,?,?)",('l2','d','case_location','nanaimo','case','cd',.08,0,now));
   c.execute("INSERT INTO published_judgments VALUES(?,?)",('j1','2010-01-01'));c.execute("INSERT INTO published_judgments VALUES(?,?)",('j2','2020-01-01'));c.execute("INSERT INTO person_identity_signals VALUES(?,?,?,?,?,?,?,?,?)",('a1','a','published_age','30','judgment','j1',.18,0,now));c.execute("INSERT INTO person_identity_signals VALUES(?,?,?,?,?,?,?,?,?)",('a2','b','published_age','55','judgment','j2',.18,0,now));c.commit()
   count=m.build_identity_candidates(c);check(count>=1,'candidate generated')
   ad=c.execute("SELECT * FROM identity_candidates WHERE (person_a='a' AND person_b='d') OR (person_a='d' AND person_b='a')").fetchone();check(ad and 'shared location' in ad['reasons'],'location history contributes evidence')
   ab=c.execute("SELECT * FROM identity_candidates WHERE (person_a='a' AND person_b='b') OR (person_a='b' AND person_b='a')").fetchone();check(not ab or 'impossible age timeline' in ab['reasons'],'date-specific age plausibility conflict applied')
   ac=c.execute("SELECT reasons FROM identity_candidates WHERE (person_a='a' AND person_b='c') OR (person_a='c' AND person_b='a')").fetchone();check(not ac or 'conflicting birth year' in ac['reasons'],'birth-year conflict applied')
 print('Person-search regression tests passed.')
if __name__=='__main__':main()
