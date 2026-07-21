import importlib.util, sqlite3, tempfile, unittest
from pathlib import Path

SPEC=importlib.util.spec_from_file_location("search_api", Path(__file__).parents[1]/"tools"/"search_api.py")
M=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)

class NameStatusTests(unittest.TestCase):
    def test_blank_status_is_treated_as_current(self):
        c=sqlite3.connect(":memory:"); c.row_factory=sqlite3.Row
        c.execute("CREATE TABLE search_records(record_id TEXT, entity_type TEXT, title TEXT, names TEXT, court_file_number TEXT, offences TEXT, court TEXT, location TEXT, outcome TEXT, verification TEXT, record_date TEXT, record_status TEXT, payload_json TEXT, indexed_at TEXT)")
        payload='{"id":"p1","type":"person","title":"Jane Smith","names":["Jane Smith"]}'
        c.execute("INSERT INTO search_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('p1','person','Jane Smith','Jane Smith','','','','','','review','','',payload,''))
        result=M.search(c,{'q':['Jane Smith'],'recordStatus':['current'],'group':['false']})
        self.assertEqual(result['total'],1)

if __name__=='__main__': unittest.main()
