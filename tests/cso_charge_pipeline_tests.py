import importlib.util,sqlite3,tempfile,json
from pathlib import Path
spec=importlib.util.spec_from_file_location('m',Path(__file__).parents[1]/'tools'/'cso_charge_pipeline.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def test_norm_file(): assert m.norm_file('12345-1')=='123451'
def test_cap_and_cache(tmp_path):
 c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
 c.execute('CREATE TABLE daily_appearances(appearance_id TEXT,court_file_number TEXT,participant_name TEXT,courthouse_name TEXT,list_date TEXT)')
 for i in range(300): c.execute('INSERT INTO daily_appearances VALUES(?,?,?,?,?)',(str(i),f"A-{i}",'Name','Court','2026-07-20'))
 old_data,old_inbox=m.DATA,m.INBOX;m.DATA=tmp_path/'data';m.INBOX=tmp_path/'inbox'
 try:r=m.prepare_queue(c,250);assert r['queued']==250
 finally:m.DATA,m.INBOX=old_data,old_inbox
