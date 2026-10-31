import sys, os, json, sqlite3, re, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.store import get_kv, session_scope, list_entities
from app.services.application_assistant.job_matching import match_job
from app.services.application_assistant.persistence import save_autopilot_job, cached_autopilot_jobs

def norm(s): return re.sub(r"\s+", " ", (s or "").lower().strip())

def main():
    with session_scope() as db:
        profile = get_kv(db, "profile") or {}
        documents = get_kv(db, "documents") or {}
        accomplishments = list_entities(db, "accomplishment") or []

    conn = sqlite3.connect("data/career_os.db")
    dj_rows = conn.execute("SELECT payload FROM entities WHERE entity_type='aa_discovered_job'").fetchall()
    dj_jobs = [json.loads(r[0]) for r in dj_rows]

    dj_by_ct = {}
    dj_by_url = {}
    for d in dj_jobs:
        dj_by_ct.setdefault((norm(d.get("company")), norm(d.get("title"))), d)
        u = (d.get("applicationUrl") or d.get("listingUrl") or "").strip().lower()
        if u:
            dj_by_url[u] = d

    jobs = cached_autopilot_jobs()
    print("jobs:", len(jobs), "discovered:", len(dj_jobs))

    enriched = 0
    updated = 0
    t0 = time.time()
    with session_scope() as db:
        for idx, j in enumerate(jobs):
            desc = j.get("description") or ""
            if not desc:
                d = None
                key = (norm(j.get("company")), norm(j.get("title")))
                if key in dj_by_ct:
                    d = dj_by_ct[key]
                else:
                    u = (j.get("applicationUrl") or "").strip().lower()
                    if u and u in dj_by_url:
                        d = dj_by_url[u]
                if d is not None:
                    desc = d.get("description") or ""
                    if desc:
                        j["description"] = desc
                        enriched += 1

            score = float(j.get("matchScore") or 0)
            bm25 = None
            try:
                res = match_job(j, profile, documents=documents, accomplishments=accomplishments)
                score = res["overallScore"]
                bm25 = res.get("bm25Alignment")
            except Exception as e:
                print("err", j.get("id"), e)
            j["matchScore"] = score
            j["resumeMatchScore"] = score
            if bm25 is not None:
                j["bm25Alignment"] = bm25
            save_autopilot_job(db, j)
            updated += 1
            if (idx+1) % 500 == 0:
                print(f"  {idx+1}/{len(jobs)} done, elapsed {round(time.time()-t0,1)}s", flush=True)
    print(f"enriched descriptions: {enriched}")
    print(f"updated: {updated} in {round(time.time()-t0,1)}s")

if __name__ == "__main__":
    main()