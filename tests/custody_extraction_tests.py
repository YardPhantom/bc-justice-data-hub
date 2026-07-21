import importlib.util, pathlib, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('advanced_features',ROOT/'tools'/'advanced_features.py')
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
class CustodyExtractionTests(unittest.TestCase):
 def test_wide_form(self):
  rows=list(mod._custody_metric_fields({'Year':'2024','Average daily population':'2,145','Remand occupancy %':'87.5%'}))
  self.assertIn(('Average daily population',2145.0,'count'),rows)
  self.assertIn(('Remand occupancy %',87.5,'percent'),rows)
 def test_long_form(self):
  rows=list(mod._custody_metric_fields({'Indicator':'Admissions to custody','Value':'1,204','Fiscal year':'2023/24'}))
  self.assertIn(('Admissions to custody',1204.0,'count'),rows)
 def test_identifiers_not_counted(self):
  self.assertEqual(list(mod._custody_metric_fields({'Year':2024,'Dataset ID':123,'Facility':'Test'})),[])
if __name__=='__main__': unittest.main()
