"""Backfill resumeMatchScore (cheap local BM25 + hybrid) for every autopilot job.

Run from apps/api:
    python scripts/compute_resume_match.py
Stores the score into each job's payload in the DB so the "resume" sort is
a plain column sort (low latency).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.store import get_kv, session_scope, list_entities
from app.services.application_assistant.candidate_match_context import (
    extract_keywords, normalize_profile_skills, extract_resume_text,
    work_experience_text, build_candidate_skill_terms, accomplishment_text,
)
from app.services.application_assistant.persistence import save_autopilot_job, cached_autopilot_jobs
from app.services.resume_intelligence.bm25 import BM25Index

def main():
    with session_scope() as db:
        profile = get_kv(db, "profile") or {}
        documents = get_kv(db, "documents") or {}
        accomplishments = list_entities(db, "accomplishment") or []

    resume_corpus = " ".join([
        extract_resume_text(documents) if documents else "",
        work_experience_text(profile),
        accomplishment_text(accomplishments),
        " ".join(normalize_profile_skills(profile)),
    ])
    resume_tokens = tuple(extract_keywords(resume_corpus))
    profile_skills = build_candidate_skill_terms(profile, documents=documents, accomplishments=accomplishments)

    jobs = cached_autopilot_jobs()
    print("jobs:", len(jobs), "accomplishments:", len(accomplishments))

    updated = 0
    with session_scope() as db:
        for j in jobs:
            try:
                job_text = (j.get("title") or "") + " " + (j.get("description") or "")
                job_tokens = tuple(extract_keywords(job_text))
                if not resume_tokens or not job_tokens:
                    sc = float(j.get("matchScore") or 0)
                else:
                    index = BM25Index.build([resume_tokens, job_tokens])
                    bm25_raw = index.score(job_tokens, 0)
                    max_score = 0.0
                    for term in set(job_tokens):
                        idf = index._idf.get(term, 0.0)
                        max_score += idf * (index.k1 + 1)
                    bm25_alignment = (bm25_raw / max_score * 100.0) if max_score > 0 else 0.0
                    bm25_alignment = min(100.0, max(0.0, bm25_alignment))
                    job_keywords = set(extract_keywords(job_text))
                    overlap = profile_skills & job_keywords
                    skill_overlap = len(overlap) / max(len(job_keywords), 1) * 100 if job_keywords else 0.0
                    sc = round(bm25_alignment * 0.4 + skill_overlap * 0.6, 1)
                j["resumeMatchScore"] = sc
                save_autopilot_job(db, j)
                updated += 1
            except Exception as e:
                print("err", j.get("id"), e)
    print("updated:", updated)

if __name__ == "__main__":
    main()