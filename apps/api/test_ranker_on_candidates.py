import sqlite3
import json
import sys

from app.db.store import session_scope, get_kv, list_entities
from app.services.application_assistant.persistence import list_autopilot_jobs, list_discovered_jobs
from app.services.application_assistant.job_filter_ranker import filter_and_rank_jobs

with session_scope() as db:
    existing_autopilot = list_autopilot_jobs(db)
    profile = get_kv(db, "profile") or {}
    documents = get_kv(db, "documents") or {}
    accomplishments = list_entities(db, "accomplishment")
    discovered = list_discovered_jobs(db, active_only=True, exclude_demo=True)

already_queued_job_ids = {j.get("jobId") for j in existing_autopilot}
candidates = [j for j in discovered if j.get("id") not in already_queued_job_ids]
print(f"Candidates: {len(candidates)}")

precomputed = {
    str(j["id"]): j["mistralMatch"] for j in candidates if isinstance(j.get("mistralMatch"), dict)
}
print(f"Precomputed matches: {len(precomputed)}")

ranked = filter_and_rank_jobs(
    existing_autopilot, candidates, profile, {}, precomputed_matches=precomputed,
    documents=documents, accomplishments=accomplishments,
)
print(f"Ranked result count: {len(ranked)}")
if ranked:
    print("Top 3 ranked:")
    for r in ranked[:3]:
        print(" -", r.get("company"), r.get("title"), "Score:", r.get("matchScore"), "URL:", r.get("applicationUrl") or r.get("listingUrl"))
