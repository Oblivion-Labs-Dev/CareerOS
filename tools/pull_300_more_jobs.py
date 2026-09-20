import sys
import asyncio
import re
from urllib.parse import urlparse
from datetime import datetime, timezone
import httpx

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"CareerOS/apps/api")

from app.db.store import session_scope, get_kv, now_iso, new_id
from app.services.job_discover import store as jd_store
from app.services.application_assistant.persistence import (
    list_discovered_jobs,
    list_autopilot_jobs,
    save_autopilot_job,
    _canonical_url_key,
    _composite_job_key,
)
from app.services.application_assistant.job_filter_ranker import (
    role_location_priority_bonus,
    queue_priority_score,
)

import json
from pathlib import Path

# New sources
from app.services.job_discover.sources.themuse import TheMuseSource
from app.services.job_discover.sources.remoteok import RemoteOKSource
from app.services.job_discover.sources.jobicy import JobicySource
from app.services.job_discover.sources.arbeitnow import ArbeitnowSource

ITAR_OR_EXCLUDED_COMPANIES = {
    "spacex", "anduril", "anduril industries", "lockheed", "northrop",
    "raytheon", "l3harris", "bae systems", "general dynamics", "palantir defense",
    "sierra nevada", "alaska airlines", "alaska air", "roblox",
}

PROHIBITED_DOMAINS = {
    "linkedin.com", "www.linkedin.com", "indeed.com", "www.indeed.com",
    "glassdoor.com", "myworkdayjobs.com",
}

INTL_KEYWORDS = {
    "argentina", "poland", "germany", "uk", "united kingdom", "london",
    "canada", "toronto", "vancouver", "india", "japan", "brazil", "mexico",
    "spain", "ireland", "dublin", "latam", "emea", "apac", "australia",
    "netherlands", "france", "portugal", "sweden", "czech", "hungary",
    "romania", "bulgaria", "serbia", "israel", "taiwan", "korea", "china",
    "philippines", "singapore", "vietnam", "colombia", "chile", "nigeria",
    "paris", "berlin", "amsterdam", "warsaw", "tokyo", "sydney",
}

NON_SWE = (
    "product manager", "sales engineer", "solutions architect", "designer",
    "recruiter", "account executive", "business analyst", "operations manager",
    "counsel", "legal", "marketing", "compliance", "auditor", "customer success",
)

SWE = (
    "software", "engineer", "developer", "backend", "frontend", "fullstack",
    "full stack", "platform", "infrastructure", "systems", "cloud", "data",
    "site reliability", "sre", "machine learning", "ai", "firmware", "devops",
)

def is_us_location(loc: str) -> tuple[bool, bool]:
    if not loc:
        return True, False
    l_low = loc.lower().strip()
    if any(k in l_low for k in INTL_KEYWORDS):
        return False, False
    is_dc = any(k in l_low for k in ("district of columbia", "washington, d.c", "washington d.c", "washington, dc", "washington dc"))
    is_wa = not is_dc and any(k in l_low for k in ("seattle", "bellevue", "redmond", "kirkland", "spokane", "tacoma", ", wa", "wa,", "wa ", "washington"))
    return True, is_wa

async def main():
    target_add = 300
    print(f"=== PULLING {target_add} MORE JOBS INTO QUEUE ===")
    
    with session_scope() as db:
        all_autopilot = list_autopilot_jobs(db)
        queued_jobs = [j for j in all_autopilot if j.get("status") == "QUEUED"]
        print(f"Current QUEUED count before pull: {len(queued_jobs)}")
        
        seen_urls = set()
        seen_composite = set()
        for j in all_autopilot:
            u = j.get("applicationUrl") or j.get("listingUrl") or j.get("url") or ""
            uk = _canonical_url_key(u)
            if uk: seen_urls.add(uk)
            c = j.get("company") or ""
            t = j.get("title") or ""
            seen_composite.add(_composite_job_key(c, t, u))
            
        candidates_pool = []
        seen_cand_urls = set()
        seen_cand_comp = set()
        
        def add_if_eligible(company, title, location, url, disc_id, score, date_val, source_provider):
            c = (company or "").strip()
            t = (title or "").strip()
            u = (url or "").strip()
            loc = (location or "").strip()
            if not c or not t or not u:
                return
            uk = _canonical_url_key(u)
            comp = _composite_job_key(c, t, u)
            if (uk and uk in seen_urls) or comp in seen_composite:
                return
            if (uk and uk in seen_cand_urls) or comp in seen_cand_comp:
                return
            netloc = urlparse(u).netloc.lower()
            if any(p in netloc for p in PROHIBITED_DOMAINS) or "myworkdayjobs" in netloc:
                return
            if any(ic in c.lower() for ic in ITAR_OR_EXCLUDED_COMPANIES):
                return
            t_low = t.lower()
            if any(m in t_low for m in NON_SWE):
                return
            if not any(w in t_low for w in SWE):
                return
            is_us, is_wa = is_us_location(loc)
            if not is_us:
                return
                
            seen_cand_urls.add(uk)
            seen_cand_comp.add(comp)
            
            is_senior = any(w in t_low for w in ("senior", "sr.", "sr ", "sr-", "staff", "principal", "lead"))
            cand = {
                "company": c,
                "title": t,
                "location": loc,
                "url": u,
                "disc_id": disc_id,
                "score": float(score) if score else 85.0,
                "date": str(date_val or ""),
                "sourceProvider": source_provider,
                "is_wa": is_wa,
                "is_us": is_us,
                "is_senior": is_senior,
            }
            cand["priorityBonus"] = role_location_priority_bonus(cand)
            candidates_pool.append(cand)
            
        # 1. Existing discovered jobs
        for j in list_discovered_jobs(db, active_only=False, exclude_demo=True):
            add_if_eligible(
                j.get("company"), j.get("title"), j.get("location"),
                j.get("applicationUrl") or j.get("listingUrl"),
                j.get("id"), j.get("matchScore") or j.get("scraperRelevancyScore"),
                j.get("datePosted") or j.get("dateDiscovered"), "discovered"
            )
            
        # 2. Existing snapshot jobs
        for j in jd_store.get_snapshot(db).get("jobs", []):
            add_if_eligible(
                j.get("companyName") or j.get("company"), j.get("title"), j.get("location"),
                j.get("url") or j.get("applyUrl"),
                j.get("id"), j.get("relevancyScore"),
                j.get("postingDate") or j.get("datePosted") or j.get("updatedAt"), "snapshot"
            )
            
        print(f"Candidates from local DB/snapshot: {len(candidates_pool)}")
        
        # 3. If needed, fetch fresh public sources
        if len(candidates_pool) < target_add:
            print("Fetching fresh postings from keyless public sources...")
            async with httpx.AsyncClient(timeout=20.0) as client:
                for src in [TheMuseSource(), RemoteOKSource(), JobicySource(), ArbeitnowSource()]:
                    try:
                        jobs = await src.fetch_jobs(client)
                        print(f"  {src.name}: fetched {len(jobs)} postings")
                        for nj in jobs:
                            add_if_eligible(
                                nj.company, nj.title, nj.location,
                                nj.apply_url or nj.source_url or nj.canonical_url,
                                nj.id, 85.0,
                                nj.first_published or nj.updated_at, src.id
                            )
                    except Exception as exc:
                        print(f"  {src.name} fetch error: {exc}")

        # 4. If still needed, query Greenhouse and Lever public boards from company_config.json
        if len(candidates_pool) < target_add:
            print("Fetching from direct Greenhouse and Lever company boards...")
            cfg_path = Path("CareerOS/apps/api/data/job_discover/company_config.json")
            if cfg_path.exists():
                cfg_data = json.loads(cfg_path.read_text(encoding="utf-8"))
                gh_dict = cfg_data.get("greenhouse", {})
                lever_dict = cfg_data.get("lever", {})

                async with httpx.AsyncClient(timeout=10.0) as client:
                    for comp_name, slug in gh_dict.items():
                        if len(candidates_pool) >= target_add + 150:
                            break
                        if any(ic in comp_name.lower() for ic in ITAR_OR_EXCLUDED_COMPANIES):
                            continue
                        gh_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
                        try:
                            resp = await client.get(gh_url)
                            if resp.status_code == 200:
                                gh_data = resp.json()
                                for g_job in gh_data.get("jobs", []):
                                    g_title = g_job.get("title", "")
                                    g_url = g_job.get("absolute_url", "")
                                    g_loc = g_job.get("location", {}).get("name", "") if isinstance(g_job.get("location"), dict) else str(g_job.get("location") or "")
                                    g_date = g_job.get("updated_at", "")
                                    add_if_eligible(comp_name, g_title, g_loc, g_url, f"gh_{slug}_{g_job.get('id')}", 90.0, g_date, "greenhouse")
                        except Exception:
                            pass

                    for comp_name, slug in lever_dict.items():
                        if len(candidates_pool) >= target_add + 150:
                            break
                        if any(ic in comp_name.lower() for ic in ITAR_OR_EXCLUDED_COMPANIES):
                            continue
                        lev_url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
                        try:
                            resp = await client.get(lev_url)
                            if resp.status_code == 200:
                                lev_data = resp.json()
                                if isinstance(lev_data, list):
                                    for l_job in lev_data:
                                        l_title = l_job.get("text", "")
                                        l_url = l_job.get("hostedUrl") or l_job.get("applyUrl") or ""
                                        cats = l_job.get("categories") or {}
                                        l_loc = cats.get("location", "")
                                        l_date = l_job.get("createdAt")
                                        add_if_eligible(comp_name, l_title, l_loc, l_url, f"lev_{slug}_{l_job.get('id')}", 90.0, l_date, "lever")
                        except Exception:
                            pass
                        
        print(f"Total eligible candidate pool: {len(candidates_pool)}")
        
        # Sort candidates by tier
        tier1_wa_senior = [c for c in candidates_pool if c["is_wa"] and c["is_senior"]]
        tier2_us_senior = [c for c in candidates_pool if not c["is_wa"] and c["is_senior"]]
        tier3_wa_swe = [c for c in candidates_pool if c["is_wa"] and not c["is_senior"]]
        tier4_us_swe = [c for c in candidates_pool if not c["is_wa"] and not c["is_senior"]]
        
        print(f"  Tier 1 (WA Senior SWE): {len(tier1_wa_senior)}")
        print(f"  Tier 2 (US Senior SWE): {len(tier2_us_senior)}")
        print(f"  Tier 3 (WA Other SWE): {len(tier3_wa_swe)}")
        print(f"  Tier 4 (US Other SWE): {len(tier4_us_swe)}")
        
        for t_list in [tier1_wa_senior, tier2_us_senior, tier3_wa_swe, tier4_us_swe]:
            t_list.sort(key=lambda x: x["date"], reverse=True)
            
        selected = []
        for t_list in [tier1_wa_senior, tier2_us_senior, tier3_wa_swe, tier4_us_swe]:
            rem = target_add - len(selected)
            if rem <= 0:
                break
            selected.extend(t_list[:rem])
            
        print(f"\nEnqueueing {len(selected)} new jobs into aa_autopilot_job...")
        now = now_iso()
        enqueued_count = 0
        for cand in selected:
            job_id = new_id("apjob_")
            payload = {
                "id": job_id,
                "jobId": cand.get("disc_id") or new_id("job_"),
                "company": cand["company"],
                "title": cand["title"],
                "roleTitle": cand["title"],
                "location": cand["location"],
                "applicationUrl": cand["url"],
                "listingUrl": cand["url"],
                "applyUrl": cand["url"],
                "url": cand["url"],
                "status": "QUEUED",
                "matchScore": cand["score"],
                "postingDate": cand["date"],
                "source": cand["sourceProvider"],
                "discoveredJobId": cand.get("disc_id"),
                "metadata": {
                    "location": cand["location"],
                    "priorityBonus": cand["priorityBonus"],
                    "postingDate": cand["date"],
                    "enqueuedReason": "user_pull_300_more",
                },
                "discoveredAt": now,
                "queuedAt": now,
                "updatedAt": now,
                "createdAt": now,
                "attemptCount": 0,
            }
            payload["queuePriority"] = queue_priority_score(payload)
            save_autopilot_job(db, payload)
            enqueued_count += 1
            
        print(f"Successfully enqueued {enqueued_count} jobs!")
        
        all_after = list_autopilot_jobs(db)
        queued_after = [j for j in all_after if j.get("status") == "QUEUED"]
        print(f"\n=== QUEUE DEPTH UPDATE ===")
        print(f"Previous QUEUED: {len(queued_jobs)}")
        print(f"Added: {enqueued_count}")
        print(f"New Total QUEUED: {len(queued_after)}")

if __name__ == "__main__":
    asyncio.run(main())
