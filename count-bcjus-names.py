from __future__ import annotations
import json, re, sqlite3
from pathlib import Path

ROOT = Path.cwd()
DB = ROOT / 'database' / 'bc_justice.db'
DATA = ROOT / 'data'
NAME_FIELDS = {
    'display_name','normalized_name','exact_name','participant_name','name','names',
    'person_name','accused_name','full_name','alias_text','title'
}

def clean(value):
    if value is None:
        return []
    if isinstance(value, list):
        out=[]
        for x in value: out.extend(clean(x))
        return out
    if not isinstance(value, str): return []
    value=' '.join(value.split()).strip(' ,;|')
    if not value: return []
    # Split only common multi-name separators; preserve hyphenated/apostrophe names.
    parts=re.split(r'\s*(?:\||;|\band\b)\s*', value, flags=re.I)
    return [p for p in parts if len(p)>=2 and any(ch.isalpha() for ch in p)]

def norm(value):
    return re.sub(r'[^a-z0-9]+',' ',value.lower()).strip()

def valid_person_name(value):
    n=norm(value)
    if not n or len(n)<3: return False
    words=n.split()
    # Keep one-word names because court data can contain surnames only, but reject obvious labels.
    blocked={'unknown','anonymous','anonymized','publication ban','not available','n a','court','statistics','records'}
    return n not in blocked and not n.isdigit()

def table_exists(c,t):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone() is not None

def cols(c,t):
    return {r[1] for r in c.execute(f'PRAGMA table_info("{t}")')}

sql_sets={}
if DB.exists():
    c=sqlite3.connect(DB)
    checks={
        'people': ['display_name','normalized_name'],
        'person_mentions': ['exact_name','normalized_name'],
        'person_aliases': ['alias_text','normalized_alias'],
        'daily_appearances': ['participant_name'],
        'search_records': ['names'],
    }
    for table, fields in checks.items():
        names=set()
        if table_exists(c,table):
            available=[f for f in fields if f in cols(c,table)]
            if available:
                q='SELECT '+','.join('"'+f+'"' for f in available)+f' FROM "{table}"'
                for row in c.execute(q):
                    for val in row:
                        for item in clean(val):
                            if valid_person_name(item): names.add(norm(item))
        sql_sets[table]=names
    c.close()
else:
    print(f'ERROR: Database not found: {DB}')

json_sets={}
def walk(obj, bucket):
    if isinstance(obj, dict):
        for k,v in obj.items():
            if k.lower() in NAME_FIELDS:
                for item in clean(v):
                    if valid_person_name(item): bucket.add(norm(item))
            walk(v,bucket)
    elif isinstance(obj,list):
        for v in obj: walk(v,bucket)

if DATA.exists():
    for path in sorted(DATA.glob('*.json')):
        bucket=set()
        try:
            walk(json.loads(path.read_text(encoding='utf-8')),bucket)
        except Exception:
            continue
        if bucket: json_sets[path.name]=bucket

sql_all=set().union(*sql_sets.values()) if sql_sets else set()
json_all=set().union(*json_sets.values()) if json_sets else set()

print('\nBCJUS PERSON-NAME AUDIT')
print('='*55)
print(f'Database: {DB}')
print('\nSQL distinct normalized names:')
for k,v in sql_sets.items(): print(f'  {k:22} {len(v):8,}')
print(f'  {"SQL UNION":22} {len(sql_all):8,}')
print('\nJSON distinct normalized names:')
for k,v in sorted(json_sets.items(), key=lambda x:(-len(x[1]),x[0])):
    print(f'  {k:32} {len(v):8,}')
print(f'  {"JSON UNION":32} {len(json_all):8,}')
print('\nCoverage:')
print(f'  SQL names present in JSON:       {len(sql_all & json_all):8,}')
print(f'  SQL names missing from JSON:     {len(sql_all - json_all):8,}')
print(f'  JSON names not found in SQL:     {len(json_all - sql_all):8,}')
print(f'  Search-record names in SQL:      {len(sql_sets.get("search_records",set())):8,}')
print(f'  Person mentions in SQL:          {len(sql_sets.get("person_mentions",set())):8,}')
print(f'  Daily court-list names in SQL:   {len(sql_sets.get("daily_appearances",set())):8,}')

missing=sorted(sql_all-json_all)[:30]
if missing:
    print('\nFirst 30 SQL names missing from JSON exports:')
    for n in missing: print('  -',n)
