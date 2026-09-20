"""Run: python scripts/firefox_uat.py --engines firefox camoufox.

Default: synthetic contact data, local form contracts, fixture-only submission.
--review-db reads a bounded real review snapshot and exercises it locally.
--live-preview opens those exact URLs only with --allow-origin; no live writes.
"""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
from urllib.parse import urlsplit

API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))
from app.services.uat.database import ReviewAdapter
from app.services.uat.firefox import BrowserConfig, TargetPolicy, FirefoxUAT
from app.services.uat.fixtures import fixture_server

SYNTHETIC = {'firstName':'Test','lastName':'Candidate','fullName':'Test Candidate','email':'test@example.invalid',
             'phone':'2065550100','country':'United States','linkedin':'https://example.invalid/test'}


async def run_case(engine, url, profile, document, policy, paced=False, portal='live'):
    started = time.perf_counter()
    row = {'targetDomain':urlsplit(url).hostname, 'contract':portal, 'runtimeEngine':engine,
           'formCompletionStatus':'not_started', 'submissionStatus':'not_attempted', 'live':not policy.fixture}
    try:
        async with asyncio.timeout(120):
            async with FirefoxUAT(BrowserConfig(engine=engine, paced=paced, proxy_url=os.getenv('CAREEROS_UAT_PROXY')),policy) as browser:
                row['telemetry'] = await browser.open(url)
                row['signature'] = await browser.signature()
                row['browserVersion'] = browser.browser.version
                if row['telemetry']['verification']=='challenge_or_lock':
                    row['formCompletionStatus']='blocked_for_review'
                else:
                    if portal=='himalayas':
                        await browser.page.frame_locator('iframe').locator('form').wait_for()
                    result = await browser.execute_form_fill(profile,document)
                    row.update(formCompletionStatus=result['status'], fields=result['fields'], telemetry=result['telemetry'])
                    if policy.fixture and result['status']=='complete':
                        root = browser.page.frames[-1] if portal=='himalayas' else browser.page
                        receipt = await browser.safely_commit_form(root.get_by_role('button',name='Submit fixture'),root.locator('#receipt'))
                        row['submissionStatus']='fixture_'+receipt['status']
                    elif not policy.fixture:
                        row['submissionStatus']='disabled_live_preview'
    except Exception as exc:
        # Exception messages can contain proxy credentials, selectors and PII.
        row['formCompletionStatus']='timeout' if 'Timeout' in type(exc).__name__ else 'error'
        row['errorType']=type(exc).__name__
    row['elapsedMs']=round((time.perf_counter()-started)*1000)
    return row


def summarize(rows):
    engines = {}
    for engine in sorted({r['runtimeEngine'] for r in rows}):
        sample = [r for r in rows if r['runtimeEngine']==engine]
        engines[engine] = {'cases':len(sample),'complete':sum(r['formCompletionStatus']=='complete' for r in sample),
                           'medianMs':statistics.median(r['elapsedMs'] for r in sample),
                           'challengeOrLock':sum(r.get('telemetry',{}).get('verification')=='challenge_or_lock' for r in sample)}
    passing = [name for name,value in engines.items() if value['complete']==value['cases']]
    preferred = min(passing,key=lambda name:engines[name]['medianMs']) if passing else None
    return {'engines':engines, 'fastestCompleteEngine':preferred,
            'scope':'Observed test cases only; no claim of ATS certification or detection avoidance.'}


async def execute(args):
    profiles = [SYNTHETIC]
    cases = []
    if args.review_db:
        # Configured PostgreSQL is supported; use a SELECT-only DB account too.
        from app.config import settings
        database_url = settings.career_os_database_url
        if database_url.startswith('sqlite:///./'):
            database_url = 'sqlite:///' + (API/'data/career_os.db').as_posix()
        with ReviewAdapter(database_url) as adapter:
            cases = adapter.snapshot(args.limit)
        if not cases:
            raise ValueError('No applications currently require manual review.')
        profiles = [case.profile for case in cases]
    if args.live_preview and (not args.review_db or not args.allow_origin):
        raise ValueError('Live preview requires --review-db and explicit --allow-origin values.')
    rows = []
    with tempfile.TemporaryDirectory(prefix='careeros-uat-') as temp:
        document = Path(args.document).resolve(strict=True) if args.document else Path(temp)/'uat-resume.pdf'
        if not args.document:
            import pymupdf
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((36,36),'CareerOS acceptance test document')
                pdf.save(document)
        if args.live_preview:
            policy = TargetPolicy(tuple(args.allow_origin))
            for case in cases:
                if not policy.allows(case.url):
                    rows.append({'targetDomain':urlsplit(case.url).hostname,'runtimeEngine':'not_launched',
                                 'formCompletionStatus':'origin_not_authorized','elapsedMs':0})
                    continue
                for engine in args.engines:
                    # Real attachments require an explicit file; never upload the fixture PDF to an employer.
                    rows.append(await run_case(engine,case.url,case.profile,document if args.document else None,policy,args.paced))
        else:
            with fixture_server() as url:
                policy = TargetPolicy((url,),fixture=True)
                for profile in profiles:
                    for portal in ('greenhouse','lever','himalayas'):
                        for engine in args.engines:
                            rows.append(await run_case(engine,url+'/'+portal,profile,document,policy,args.paced,portal))
    report = {'schemaVersion':1,'createdAt':datetime.now(timezone.utc).isoformat(),
              'profileSource':'manual_review_snapshot' if args.review_db else 'synthetic',
              'cases':rows,'summary':summarize(rows)}
    output = Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary = output.with_suffix(output.suffix+'.tmp')
    temporary.write_text(json.dumps(report,indent=2),encoding='utf-8')
    temporary.replace(output)
    print(json.dumps(report['summary']))
    return 0 if rows and all(row['formCompletionStatus']=='complete' for row in rows) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engines',nargs='+',choices=['firefox','camoufox'],default=['firefox'])
    parser.add_argument('--review-db',action='store_true')
    parser.add_argument('--live-preview',action='store_true')
    parser.add_argument('--allow-origin',action='append',default=[])
    parser.add_argument('--limit',type=int,default=3)
    parser.add_argument('--document')
    parser.add_argument('--paced',action='store_true')
    parser.add_argument('--output',default=str(API/'data/uat/latest.json'))
    args=parser.parse_args()
    try:
        return asyncio.run(execute(args))
    except Exception as exc:
        print(json.dumps({'status':'setup_error','errorType':type(exc).__name__}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
