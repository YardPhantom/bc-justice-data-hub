import csv
import io
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

from collect_statcan_crime import CHECK_INTERVAL_DAYS, CountingReader, csv_info, progress_bar


class StatCanStreamingTests(unittest.TestCase):
    def test_csv_stream_reads_without_full_extraction(self):
        archive = io.BytesIO()
        content = 'REF_DATE,GEO,VALUE\n2024,British Columbia,1\n2025,British Columbia,2\n'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('35100184.csv', content)
        with zipfile.ZipFile(io.BytesIO(archive.getvalue())) as zf:
            info = csv_info(zf)
            counter = CountingReader(zf.open(info, 'r'))
            text = io.TextIOWrapper(io.BufferedReader(counter), encoding='utf-8-sig', newline='')
            rows = list(csv.DictReader(text))
            self.assertEqual(2, len(rows))
            self.assertEqual(info.file_size, counter.bytes_read)

    def test_complete_progress_bar_is_full(self):
        self.assertEqual('[####################]', progress_bar(100, 100))

    def test_large_incident_table_uses_monthly_cache_window(self):
        self.assertEqual(30, CHECK_INTERVAL_DAYS['35100184'])


if __name__ == '__main__':
    unittest.main()
