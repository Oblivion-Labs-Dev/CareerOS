import sys
from collections import defaultdict
import re

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"CareerOS/apps/api")

from app.db.store import session_scope
from app.services.application_assistant.persistence import (
    list_autopilot_jobs,
    _canonical_url_key,
    _composite_job_key,
)

with session_scope() as db:
    all_jobs = list_autopilot_jobs(db)
    submitted = [j for j in all_jobs if (j.get("status") or "").upper() == "SUBMITTED"]
    print(f"Total jobs in DB: {len(all_jobs)}")
    print(f"Total SUBMITTED rows: {len(submitted)}")

    # 1. Exact Canonical URL duplicates
    by_url = defaultdict(list)
    for j in submitted:
        u = j.get("applicationUrl") or j.get("listingUrl") or j.get("url") or ""
        uk = _canonical_url_key(u)
        if uk:
            by_url[uk].append(j)

    url_dups = {k: v for k, v in by_url.items() if len(v) > 1}
    print(f"\n--- 1. DUPLICATE CANONICAL URLS AMONG SUBMITTED ---")
    print(f"Unique URLs with >1 submission: {len(url_dups)}")
    for k, v in list(url_dups.items())[:10]:
        print(f"  URL: {k} (count={len(v)})")
        for item in v:
            print(f"    - ID: {item.get('id')} | Company: {item.get('company')} | Title: {item.get('title')} | Date: {item.get('postingDate')} | SubmittedAt: {item.get('submittedAt')}")

    # 2. Duplicate (Company, Title)
    by_ct = defaultdict(list)
    for j in submitted:
        c = re.sub(r"(inc|llc|corp|corporation|ltd|co)\b", "", (j.get("company") or "").lower()).strip()
        t = re.sub(r"\s+", " ", (j.get("title") or "").lower()).strip()
        by_ct[(c, t)].append(j)

    ct_dups = {k: v for k, v in by_ct.items() if len(v) > 1}
    print(f"\n--- 2. DUPLICATE (COMPANY, TITLE) AMONG SUBMITTED ---")
    print(f"Unique (Company, Title) pairs with >1 submission: {len(ct_dups)}")
    for (c, t), v in list(ct_dups.items())[:10]:
        print(f"  Company: '{c}' | Title: '{t}' (count={len(v)})")
        for item in v:
            u = item.get("applicationUrl") or item.get("listingUrl") or item.get("url") or ""
            print(f"    - ID: {item.get('id')} | URL: {u} | Date: {item.get('postingDate')} | SubmittedAt: {item.get('submittedAt')}")

    # 3. Duplicate (Company, Title, PostingDate)
    by_ctd = defaultdict(list)
    for j in submitted:
        c = re.sub(r"(inc|llc|corp|corporation|ltd|co)\b", "", (j.get("company") or "").lower()).strip()
        t = re.sub(r"\s+", " ", (j.get("title") or "").lower()).strip()
        d = (j.get("postingDate") or "").strip()
        by_ctd[(c, t, d)].append(j)

    ctd_dups = {k: v for k, v in by_ctd.items() if len(v) > 1}
    print(f"\n--- 3. DUPLICATE (COMPANY, TITLE, POSTING_DATE) AMONG SUBMITTED ---")
    print(f"Unique (Company, Title, Date) triples with >1 submission: {len(ctd_dups)}")
    for (c, t, d), v in list(ctd_dups.items())[:10]:
        print(f"  Company: '{c}' | Title: '{t}' | Date: '{d}' (count={len(v)})")
        for item in v:
            u = item.get("applicationUrl") or item.get("listingUrl") or item.get("url") or ""
            print(f"    - ID: {item.get('id')} | URL: {u} | SubmittedAt: {item.get('submittedAt')}")

    # 4. Duplicate (Company, Title, URL)
    by_ctu = defaultdict(list)
    for j in submitted:
        c = (j.get("company") or "").strip().lower()
        t = (j.get("title") or "").strip().lower()
        u = _canonical_url_key(j.get("applicationUrl") or j.get("listingUrl") or j.get("url") or "")
        by_ctu[(c, t, u)].append(j)

    ctu_dups = {k: v for k, v in by_ctu.items() if len(v) > 1}
    print(f"\n--- 4. DUPLICATE (COMPANY, TITLE, CANONICAL_URL) AMONG SUBMITTED ---")
    print(f"Unique (Company, Title, URL) triples with >1 submission: {len(ctu_dups)}")
    for (c, t, u), v in list(ctu_dups.items())[:10]:
        print(f"  Company: '{c}' | Title: '{t}' | URL: '{u}' (count={len(v)})")
        for item in v:
            print(f"    - ID: {item.get('id')} | Date: {item.get('postingDate')} | SubmittedAt: {item.get('submittedAt')}")
