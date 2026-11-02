import sys
import json
import re
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path

# Fix encoding
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

ITAR_OR_EXCLUDED_COMPANIES = {
    "spacex", "anduril", "anduril industries", "lockheed", "northrop",
    "raytheon", "l3harris", "bae systems", "general dynamics", "palantir defense",
    "sierra nevada", "alaska airlines", "alaska air", "roblox",
}

PROHIBITED_DOMAINS = {
    "linkedin.com", "www.linkedin.com", "indeed.com", "www.indeed.com",
    "glassdoor.com", "myworkdayjobs.com",
}

US_STATE_CODES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
    "dc",
}

INTL_KEYWORDS = {
    "argentina", "poland", "germany", "uk", "united kingdom", "london",
    "canada", "toronto", "vancouver", "india", "japan", "brazil", "mexico",
    "spain", "ireland", "dublin", "latam", "emea", "apac", "australia",
    "netherlands", "france", "portugal", "sweden", "czech", "hungary",
    "romania", "bulgaria", "serbia", "israel", "taiwan", "korea", "china",
    "philippines", "singapore", "vietnam", "colombia", "chile", "nigeria",
}

NON_SWE_KEYWORDS = (
    "product manager", "sales engineer", "solutions architect", "designer",
    "recruiter", "account executive", "business analyst", "operations manager",
    "counsel", "legal", "marketing", "compliance", "auditor", "customer success",
)

SWE_KEYWORDS = (
    "software", "engineer", "developer", "backend", "frontend", "fullstack",
    "full stack", "platform", "infrastructure", "systems", "cloud", "data",
    "site reliability", "sre", "machine learning", "ai", "firmware", "devops",
)

def is_us_location(loc: str) -> tuple[bool, bool]:
    """Returns (is_us, is_wa)"""
    if not loc:
        return True, False
    l_low = loc.lower().strip()
    if any(k in l_low for k in INTL_KEYWORDS):
        return False, False
        
    is_dc = any(k in l_low for k in ("district of columbia", "washington, d.c", "washington d.c", "washington, dc", "washington dc"))
    is_wa = not is_dc and any(k in l_low for k in ("seattle", "bellevue", "redmond", "kirkland", "spokane", "tacoma", ", wa", "wa,", "wa ", "washington"))
    if is_wa:
        return True, True
        
    if any(k in l_low for k in ("united states", "usa", "u.s.", "remote", "us", "remote - us", "remote, us", "san francisco", "new york", "austin", "boston", "chicago", "denver", "los angeles", "atlanta", "sf", "distributed", "amer")):
        return True, False
        
    # Check state abbreviations like ", CA", ", TX", etc.
    tokens = re.split(r"[\s,;/-]+", l_low)
    if any(t in US_STATE_CODES for t in tokens):
        return True, ("wa" in tokens)
        
    return False, False

def main():
    target_queue_depth = 500
    print(f"=== PULLING JOBS INTO QUEUE (TARGET: ~{target_queue_depth}) ===")
    
    with session_scope() as db:
        all_autopilot = list_autopilot_jobs(db)
        queued_jobs = [j for j in all_autopilot if j.get("status") == "QUEUED"]
        current_queued_count = len(queued_jobs)
        print(f"Current QUEUED count: {current_queued_count}")
        
        needed = max(0, target_queue_depth - current_queued_count)
        if needed <= 0:
            print(f"Queue already has {current_queued_count} jobs (>= {target_queue_depth}). Nothing to add.")
            return
            
        print(f"Need to pull in ~{needed} more jobs to reach target {target_queue_depth}.")
        
        # Build deduplication sets from existing autopilot jobs
        seen_urls = set()
        seen_keys = set()
        for j in all_autopilot:
            for u in (j.get("applicationUrl"), j.get("listingUrl"), j.get("applyUrl"), j.get("url")):
                if u:
                    k = _canonical_url_key(u)
                    if k:
                        seen_urls.add(k)
            c = (j.get("company") or "").lower().strip()
            t = (j.get("title") or "").lower().strip()
            u = j.get("applicationUrl") or ""
            if c and t:
                seen_keys.add(_composite_job_key(c, t, u))
                seen_keys.add((c, t))
                
        candidates_pool = []
        seen_candidate_urls = set()
        seen_candidate_keys = set()
        
        def evaluate_and_add(raw_job, source_type):
            if source_type == "snapshot":
                url = (raw_job.get("url") or raw_job.get("applyUrl") or "").strip()
                company = (raw_job.get("companyName") or raw_job.get("company") or "").strip()
                title = (raw_job.get("title") or "").strip()
                location = (raw_job.get("location") or "").strip()
                disc_id = raw_job.get("id")
                date_val = (
                    raw_job.get("postingDate") or raw_job.get("datePosted")
                    or raw_job.get("scrapedAt") or raw_job.get("updatedAt") or ""
                )
                score = raw_job.get("relevancyScore") or 85.0
            else:
                url = (raw_job.get("applicationUrl") or raw_job.get("listingUrl") or "").strip()
                company = (raw_job.get("company") or "").strip()
                title = (raw_job.get("title") or "").strip()
                location = (raw_job.get("location") or "").strip()
                disc_id = raw_job.get("id")
                date_val = (
                    raw_job.get("datePosted") or raw_job.get("dateDiscovered")
                    or raw_job.get("updatedAt") or raw_job.get("createdAt") or ""
                )
                score = raw_job.get("scraperRelevancyScore") or raw_job.get("matchScore") or 85.0
                
            if not url or not company or not title:
                return
                
            url_key = _canonical_url_key(url)
            comp_key = (company.lower().strip(), title.lower().strip())
            composite_key = _composite_job_key(company, title, url)
            
            if (url_key and url_key in seen_urls) or (url_key and url_key in seen_candidate_urls):
                return
            if comp_key in seen_keys or composite_key in seen_keys:
                return
            if comp_key in seen_candidate_keys:
                return
                
            # Prohibited domains or ITAR
            netloc = urlparse(url).netloc.lower()
            if any(p in netloc for p in PROHIBITED_DOMAINS) or "myworkdayjobs" in netloc:
                return
            if any(ic in company.lower() for ic in ITAR_OR_EXCLUDED_COMPANIES):
                return
                
            t_low = title.lower()
            if any(m in t_low for m in NON_SWE_KEYWORDS):
                return
            if not any(w in t_low for w in SWE_KEYWORDS):
                return
                
            is_us, is_wa = is_us_location(location)
            if not is_us:
                return
                
            is_senior = any(w in t_low for w in ("senior", "sr.", "sr ", "sr-", "staff", "principal", "lead"))
            
            seen_candidate_urls.add(url_key)
            seen_candidate_keys.add(comp_key)
            
            cand_obj = {
                "company": company,
                "title": title,
                "location": location,
                "url": url,
                "date": str(date_val),
                "matchScore": float(score) if score else 85.0,
                "disc_id": disc_id,
                "is_wa": is_wa,
                "is_us": is_us,
                "is_senior": is_senior,
                "sourceProvider": "greenhouse" if "greenhouse.io" in url.lower() else "browse_jobs",
            }
            cand_obj["priorityBonus"] = role_location_priority_bonus(cand_obj)
            candidates_pool.append(cand_obj)
            
        # Add from snapshot
        for j in jd_store.get_snapshot(db).get("jobs", []):
            evaluate_and_add(j, "snapshot")
            
        # Add from discovered
        for j in list_discovered_jobs(db):
            evaluate_and_add(j, "discovered")
            
        print(f"Total eligible candidate pool found: {len(candidates_pool)}")
        
        # Partition into priority tiers
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
            rem = needed - len(selected)
            if rem <= 0:
                break
            selected.extend(t_list[:rem])
            
        print(f"\nEnqueueing {len(selected)} jobs into queue...")
        now = now_iso()
        enqueued_count = 0
        for cand in selected:
            job_id = new_id("apjob_")
            payload = {
                "id": job_id,
                "jobId": cand.get("disc_id"),
                "company": cand["company"],
                "title": cand["title"],
                "roleTitle": cand["title"],
                "location": cand["location"],
                "applicationUrl": cand["url"],
                "listingUrl": cand["url"],
                "applyUrl": cand["url"],
                "url": cand["url"],
                "status": "QUEUED",
                "matchScore": cand["matchScore"],
                "postingDate": cand["date"],
                "source": cand["sourceProvider"],
                "discoveredJobId": cand.get("disc_id"),
                "metadata": {
                    "location": cand["location"],
                    "priorityBonus": cand["priorityBonus"],
                    "postingDate": cand["date"],
                    "enqueuedReason": "user_pull_500_tier_priority",
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
        
        # Verify final counts
        all_after = list_autopilot_jobs(db)
        queued_after = [j for j in all_after if j.get("status") == "QUEUED"]
        print(f"\n=== FINAL QUEUE SUMMARY ===")
        print(f"Total QUEUED jobs: {len(queued_after)}")
        t1 = sum(1 for j in queued_after if role_location_priority_bonus(j) >= 100.0)
        t2 = sum(1 for j in queued_after if 60.0 <= role_location_priority_bonus(j) < 100.0)
        other = len(queued_after) - t1 - t2
        print(f"  Tier 1 (WA Senior SWE): {t1}")
        print(f"  Tier 2 (US Senior SWE): {t2}")
        print(f"  Other/Mid-level SWE: {other}")

if __name__ == "__main__":
    main()
