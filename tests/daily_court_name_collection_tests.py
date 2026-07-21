import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

from collect_justice_sources import discover_pdf_links, extract_daily_rows, parse_pdf


def test_discovers_pdf_links_from_actual_court_index_shape():
    html = '<a href="Nanaimo_Law_Court_Provincial.pdf">Nanaimo_Law_Court_Provincial</a><a href="Evergreen_Hall_Provincial.pdf">Evergreen Hall</a>'
    links = discover_pdf_links(html, 'https://justice.gov.bc.ca/courts/DAPCindex.html')
    assert len(links) == 2
    assert links[0][1].endswith('.pdf')


def test_layout_rows_extract_full_accused_names():
    text = """
Nanaimo Law Courts-1091 Page: 1 of 1
Public Access Adult Court List
Room: 227 Court Date: 20-JUL-2026
For the Session Commencing at 09:30 AM
  1  90642-1               Ellis, Earl Kent William                 WAR N Morino, T J 174 PI 001 CDS 5 2
  2  93206-1               Lane, Robyn Christine                    WAR N Ritzker, M G 370 PSB 001 CCC 320.14 2
"""
    rows = extract_daily_rows(text, 'Provincial Court', 'url', 'doc', 'key', 'version')
    assert [(r['court_file_number'], r['participant_name']) for r in rows] == [
        ('90642-1', 'Ellis, Earl Kent William'),
        ('93206-1', 'Lane, Robyn Christine'),
    ]
    assert all(r['legal_status'] == 'scheduled_appearance' for r in rows)
