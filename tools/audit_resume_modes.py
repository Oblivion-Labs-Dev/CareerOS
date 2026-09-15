"""Compare all tailoring modes on 12 saved JDs, without any DB writes or API calls."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/api'))
os.environ['HF_HUB_OFFLINE']='1'
from app.services.resume_intelligence.minimal_tailoring import tailor,mode_config
from app.services.resume_intelligence.baseline_document import render_baseline,approved_path
from app.services.resume_intelligence.evidence_match import compare_pdfs
from audit_resume_matching import IDS
import pymupdf


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--semantic',action='store_true')
    args=parser.parse_args()
    with sqlite3.connect('file:'+(ROOT/'apps/api/data/career_os.db').as_posix()+'?mode=ro',uri=True) as db:
        records=[json.loads(row[0]) for row in db.execute("SELECT payload FROM entities WHERE entity_type='accomplishment'")]
        profile=json.loads(db.execute("SELECT value FROM kv_store WHERE key='profile'").fetchone()[0])
        jobs=[json.loads(row[0]) for ident in IDS if (row:=db.execute('SELECT payload FROM entities WHERE id=?',(ident,)).fetchone())]
    rows=[]
    for job in jobs:
        for mode in ('off','honest','aggressive'):
            started=time.perf_counter()
            config=mode_config(mode,{**(profile.get('resumeTailoringConfig') or {}),'use_semantic':args.semantic})
            result=tailor(records,job['description'],job['title'],mode=mode,config=config)
            data=render_baseline(result)
            comparison=compare_pdfs(approved_path().read_bytes(),data,job['description'],use_semantic=args.semantic and mode!='off')
            with pymupdf.open(stream=data,filetype='pdf') as pdf:
                pages=len(pdf)
            assert pages==1
            if mode=='off':
                assert data==approved_path().read_bytes()
            rows.append({'company':job.get('company'),'title':job['title'],'mode':mode,
                         'decisions':dict(Counter(b['decision'] for b in result['resumeBullets'])),
                         'pages':pages,'eligibleReplacementCount':result['eligibleReplacementCount'],
                         'before':comparison['before']['score'],'after':comparison['after']['score'],
                         'delta':comparison['delta'],'elapsedMs':round((time.perf_counter()-started)*1000)})
    output=ROOT/'tmp/resume-match-audit/modes.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print(json.dumps({'cases':len(rows),'allOnePage':all(r['pages']==1 for r in rows),
                      'changedByMode':{m:sum(r['decisions'].get('REORDER',0)+r['decisions'].get('REPLACE',0)>0 for r in rows if r['mode']==m) for m in ('off','honest','aggressive')},
                      'scoreChanges':[{'company':r['company'],'mode':r['mode'],'delta':r['delta']} for r in rows if r['delta']]}))


if __name__=='__main__':
    main()
