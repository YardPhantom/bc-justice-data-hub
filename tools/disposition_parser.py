#!/usr/bin/env python3
"""Normalize verified conviction dispositions from official BC justice sources.

Only explicit disposition language from an official judgment, verified CSO outcome,
or manually verified review record can create a conviction outcome. Scheduled court
appearances, charges, allegations, and ambiguous references never create convictions.
"""
from __future__ import annotations
import json, re, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'database'/'bc_justice.db'

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def norm(v): return ' '.join(re.sub(r'[^a-z0-9]+',' ',str(v or '').casefold()).split())
def uid(*parts): return str(uuid.uuid5(uuid.NAMESPACE_URL,'|'.join(str(x or '') for x in parts)))
def has_table(c,name): return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())
def cols(c,name): return {r[1] for r in c.execute(f'PRAGMA table_info({name})')}
def val(row,*names):
    for name in names:
        if name in row.keys() and row[name] not in (None,''): return row[name]
    return ''

CONVICTION_PATTERNS=[
 ('guilty_plea',re.compile(r'\b(?:plead(?:ed|s)?|entered?\s+(?:a\s+)?)guilty\b(?:\s+to)?',re.I)),
 ('found_guilty',re.compile(r'\b(?:found|finds?|finding)\s+(?:the\s+(?:accused|defendant)\s+)?guilty\b',re.I)),
 ('convicted',re.compile(r'\b(?:is|was|were|has been|stands?)\s+convicted\b|\bconviction(?:s)?\s+(?:is|are|was|were|entered|recorded)\b',re.I)),
 ('sentencing',re.compile(r'\b(?:sentenced?|sentence hearing|sentencing hearing)\b.{0,100}\b(?:for|following|after)\b.{0,100}\b(?:conviction|guilty plea|found guilty)\b',re.I|re.S)),
]
NEGATIVE_PATTERNS=[
 re.compile(r'\bnot guilty\b',re.I),re.compile(r'\bacquitt(?:ed|al)\b',re.I),
 re.compile(r'\bcharge(?:s)?\s+(?:was|were|is|are)?\s*(?:stayed|withdrawn|dismissed)\b',re.I),
 re.compile(r'\bconviction\s+(?:was|is)\s+(?:set aside|overturned|quashed)\b',re.I),
]
OFFENCE_PATTERNS=[
 re.compile(r'\b(?:pleaded guilty|pled guilty|found guilty|convicted)\s+(?:on\s+)?(?:of|to)\s+([^.;\n]{3,180})',re.I),
 re.compile(r'\bsentenc(?:ed|ing)\s+(?:the\s+(?:accused|offender)\s+)?(?:for|on)\s+([^.;\n]{3,180})',re.I),
]

def classify(text):
    sample=' '.join(str(text or '').split())
    hits=[]
    for label,pat in CONVICTION_PATTERNS:
        m=pat.search(sample)
        if m:
            window=sample[max(0,m.start()-120):m.end()+240]
            if not any(p.search(window) for p in NEGATIVE_PATTERNS): hits.append((label,m.start(),window))
    if not hits:return None
    hits.sort(key=lambda x:x[1])
    offences=[]
    for pat in OFFENCE_PATTERNS:
        for m in pat.finditer(sample):
            item=re.split(r'\b(?:and was|and is|contrary to|under section|pursuant to)\b',m.group(1),maxsplit=1,flags=re.I)[0].strip(' ,:-')
            if item and len(item)<=180: offences.append(item)
    return {'disposition':hits[0][0],'evidence':hits[0][2][:500],'offences':list(dict.fromkeys(offences))[:8]}

def ensure_outcome_schema(c):
    if not has_table(c,'outcomes'):
        c.execute('''CREATE TABLE outcomes(outcome_id TEXT PRIMARY KEY,case_id TEXT,outcome_type TEXT,outcome_date TEXT,description TEXT,source_type TEXT,source_entity_id TEXT,verified INTEGER DEFAULT 0,created_at TEXT)''')
    existing=cols(c,'outcomes')
    for spec in ['description TEXT','source_type TEXT','source_entity_id TEXT','verified INTEGER DEFAULT 0','created_at TEXT']:
        if spec.split()[0] not in existing:c.execute(f'ALTER TABLE outcomes ADD COLUMN {spec}')

def ensure_case_for_judgment(c,j):
    jid=str(val(j,'judgment_id'))
    if has_table(c,'case_links'):
        linkcols=cols(c,'case_links')
        if {'case_id','linked_entity_type','linked_entity_id'}<=linkcols:
            row=c.execute("SELECT case_id FROM case_links WHERE linked_entity_type='judgment' AND linked_entity_id=? ORDER BY confidence DESC LIMIT 1",(jid,)).fetchone()
            if row:return row[0]
    citation=str(val(j,'citation'))
    title=str(val(j,'case_title','case_name','title'))
    if citation:
        row=c.execute("SELECT case_id FROM cases WHERE lower(replace(replace(coalesce(citation,''),' ',''),'.',''))=lower(replace(replace(?,' ',''),'.','')) LIMIT 1",(citation,)).fetchone()
        if row:return row[0]
    case_id=uid('judgment-case',jid)
    casecols=cols(c,'cases')
    payload={'case_id':case_id,'case_title':title or citation or 'Published judgment','citation':citation,'court_level':str(val(j,'court_level','court')),'opened_date':str(val(j,'decision_date')),'closed_date':str(val(j,'decision_date')),'legal_status':'convicted','final_outcome':'convicted','verification_state':'verified','source_type':'published_judgment','source_url':str(val(j,'source_url')),'retrieved_at':str(val(j,'retrieved_at')) or now(),'notes':'Created from explicit disposition language in an official published judgment.'}
    keys=[k for k in payload if k in casecols]
    c.execute(f"INSERT OR IGNORE INTO cases({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",tuple(payload[k] for k in keys))
    return case_id

def linked_people(c,j,case_id):
    jid=str(val(j,'judgment_id')); found=set()
    if has_table(c,'person_mentions'):
        mcols=cols(c,'person_mentions')
        if {'person_id','source_entity_id'}<=mcols:
            for r in c.execute("SELECT person_id FROM person_mentions WHERE source_entity_id=? AND person_id IS NOT NULL",(jid,)): found.add(r[0])
    if has_table(c,'case_people'):
        for r in c.execute('SELECT person_id FROM case_people WHERE case_id=?',(case_id,)): found.add(r[0])
    # Exact full-name title match only; initials and partial names are excluded.
    title=norm(val(j,'case_title','case_name','title'))
    if title and has_table(c,'people'):
        for r in c.execute("SELECT person_id,display_name FROM people WHERE length(trim(coalesce(display_name,'')))>=5"):
            n=norm(r['display_name'])
            if len(n.split())>=2 and re.search(r'(^| )'+re.escape(n)+r'( |$)',title): found.add(r['person_id'])
    return sorted(found)

def add_charge(c,case_id,offence,source_id):
    if not has_table(c,'charges') or not offence:return
    cc=cols(c,'charges'); cid=uid('judgment-charge',case_id,offence)
    payload={'charge_id':cid,'case_id':case_id,'offence_text':offence,'charge_status':'resolved','disposition':'convicted','disposition_date':'','verification_state':'verified','source_entity_id':source_id}
    keys=[k for k in payload if k in cc]
    c.execute(f"INSERT OR IGNORE INTO charges({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",tuple(payload[k] for k in keys))

def parse_judgments(c):
    if not has_table(c,'published_judgments'):return {'examined':0,'convictions':0,'peopleLinked':0,'reviewNeeded':0}
    ensure_outcome_schema(c); jc=cols(c,'published_judgments')
    for spec in ['disposition_evidence TEXT','disposition_source TEXT','disposition_parsed_at TEXT']:
        if spec.split()[0] not in jc:c.execute(f'ALTER TABLE published_judgments ADD COLUMN {spec}')
    jc=cols(c,'published_judgments')
    wanted=[x for x in ('judgment_id','case_title','case_name','title','citation','decision_date','court_level','court','source_url','retrieved_at','raw_metadata','decision_text','summary','outcome_type','verification_state','sentence_text') if x in jc]
    stats={'examined':0,'convictions':0,'peopleLinked':0,'reviewNeeded':0}
    for j in c.execute(f"SELECT {','.join(wanted)} FROM published_judgments").fetchall():
        stats['examined']+=1
        text='\n'.join(str(val(j,k)) for k in ('case_title','case_name','title','raw_metadata','decision_text','summary','sentence_text'))
        result=classify(text)
        if not result:continue
        case_id=ensure_case_for_judgment(c,j)
        people=linked_people(c,j,case_id)
        # An official judgment with explicit disposition wording verifies the outcome,
        # but a conviction event requires an exact linked person identity.
        c.execute("UPDATE published_judgments SET outcome_type='convicted',verification_state='verified',disposition_evidence=?,disposition_source='explicit judgment text',disposition_parsed_at=? WHERE judgment_id=?",(result['evidence'],now(),val(j,'judgment_id')))
        oc=cols(c,'outcomes'); oid=uid('judgment-outcome',val(j,'judgment_id'))
        payload={'outcome_id':oid,'case_id':case_id,'outcome_type':'convicted','outcome_date':str(val(j,'decision_date')),'description':result['evidence'],'source_type':'published_judgment','source_entity_id':str(val(j,'judgment_id')),'verified':1,'created_at':now()}
        keys=[k for k in payload if k in oc]
        c.execute(f"INSERT OR REPLACE INTO outcomes({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",tuple(payload[k] for k in keys))
        if 'final_outcome' in cols(c,'cases'): c.execute("UPDATE cases SET final_outcome='convicted',legal_status='convicted',verification_state='verified' WHERE case_id=?",(case_id,))
        for offence in result['offences']:add_charge(c,case_id,offence,str(val(j,'judgment_id')))
        if people:
            if has_table(c,'case_people'):
                cpcols=cols(c,'case_people')
                for pid in people:
                    values={'case_id':case_id,'person_id':pid,'role':'accused','verification_state':'verified'}; keys=[k for k in values if k in cpcols]
                    try:c.execute(f"INSERT OR IGNORE INTO case_people({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",tuple(values[k] for k in keys))
                    except sqlite3.OperationalError:pass
            stats['convictions']+=1; stats['peopleLinked']+=len(people)
        else:
            stats['reviewNeeded']+=1
            if has_table(c,'review_queue'):
                rc=cols(c,'review_queue'); rid=uid('review','judgment-person-link',val(j,'judgment_id'))
                values={'review_id':rid,'entity_type':'published_judgment','entity_id':str(val(j,'judgment_id')),'reason':'Explicit conviction found; link the convicted person identity','priority':'high','status':'open','created_at':now()}; keys=[k for k in values if k in rc]
                try:c.execute(f"INSERT OR IGNORE INTO review_queue({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",tuple(values[k] for k in keys))
                except sqlite3.OperationalError:pass
    return stats

def normalize_verified_cso(c):
    if not has_table(c,'cases'):return 0
    cc=cols(c,'cases'); needed={'case_id','verification_state'}
    if not needed<=cc:return 0
    outcome_expr="coalesce(final_outcome,legal_status,'')" if {'final_outcome','legal_status'}<=cc else ("coalesce(final_outcome,'')" if 'final_outcome' in cc else "coalesce(legal_status,'')")
    rows=c.execute(f"SELECT case_id,{outcome_expr} outcome FROM cases WHERE verification_state='verified' AND lower({outcome_expr}) IN ('convicted','guilty','guilty plea','found guilty')").fetchall()
    ensure_outcome_schema(c); oc=cols(c,'outcomes'); n=0
    for r in rows:
        oid=uid('verified-case-outcome',r['case_id']); values={'outcome_id':oid,'case_id':r['case_id'],'outcome_type':'convicted','outcome_date':'','description':'Verified case disposition','source_type':'verified_case','source_entity_id':r['case_id'],'verified':1,'created_at':now()}; keys=[k for k in values if k in oc]
        c.execute(f"INSERT OR IGNORE INTO outcomes({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",tuple(values[k] for k in keys)); n+=1
    return n

def run(c):
    result=parse_judgments(c); result['verifiedCaseOutcomes']=normalize_verified_cso(c); c.commit(); return result

def main():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    print(json.dumps(run(c),indent=2)); return 0
if __name__=='__main__':raise SystemExit(main())
