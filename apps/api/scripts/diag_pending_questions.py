"""Read-only diagnostic: pending questions on review-bucket jobs, grouped by ATS.

One-off operator script (apps/api/scripts is operator scratch). Reads
data/career_os.db directly with sqlite3 and prints a summary; writes a JSON
report to data/application_assistant/pending_questions_report.json for the
session that invoked it. No writes to the DB.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "career_os.db"
OUT = Path(__file__).resolve().parents[1] / "data" / "application_assistant" / "pending_questions_report.json"


def ats_of(url: str) -> str:
    u = (url or "").lower()
    if "greenhouse" in u:
        return "greenhouse"
    if "ashby" in u:
        return "ashby"
    if "lever" in u:
        return "lever"
    if "workday" in u:
        return "workday"
    if "smartrecruiters" in u:
        return "smartrecruiters"
    if not u:
        return "none"
    m = re.search(r"https?://([^/:]+)", u)
    return "other:" + (m.group(1) if m else u[:40])


def main() -> None:
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT id, payload FROM entities WHERE entity_type='aa_autopilot_job'"
    ).fetchall()
    conn.close()

    review_jobs = []
    for _id, raw in rows:
        p = json.loads(raw)
        status = p.get("status")
        if status not in ("NEEDS_REVIEW", "MANUAL_REVIEW"):
            continue
        pq = p.get("pendingQuestions") or p.get("unresolvedQuestions") or []
        review_jobs.append(
            {
                "id": p.get("id"),
                "status": status,
                "company": p.get("company"),
                "title": p.get("title"),
                "ats": ats_of(p.get("applicationUrl") or ""),
                "hasPersistentBlock": p.get("hasPersistentBlock"),
                "reasonCategory": p.get("reasonCategory"),
                "matchScore": p.get("matchScore"),
                "pending": [
                    {
                        "question": (q.get("question") or q.get("rawLabel") or "")[:200],
                        "fieldType": q.get("fieldType"),
                        "options": q.get("options") or [],
                        "required": q.get("required", True),
                    }
                    for q in pq
                    if isinstance(q, dict)
                    and (q.get("question") or q.get("rawLabel"))
                    and not re.search(r"\bpass\s?word\b", str(q.get("question") or q.get("rawLabel") or ""), re.I)
                ],
            }
        )

    status_counts = Counter(j["status"] for j in review_jobs)
    with_pending = [j for j in review_jobs if j["pending"]]
    ats_counts = Counter(j["ats"] for j in with_pending)
    by_ats_status = Counter((j["ats"], j["status"]) for j in review_jobs)

    senior_ai = [j for j in with_pending if re.search(r"(senior|sr\.)\s*ai|ai\s*engineer|machine learning|ml engineer", j["title"] or "", re.I)]

    report = {
        "statusCounts": dict(status_counts),
        "withPendingByAts": dict(ats_counts),
        "reviewJobsByAts": {f"{a}|{s}": c for (a, s), c in sorted(by_ats_status.items(), key=lambda kv: -kv[1])},
        "withPendingCount": len(with_pending),
        "seniorAiCount": len(senior_ai),
        "seniorAi": senior_ai[:60],
        "allWithPending": sorted(with_pending, key=lambda j: -(j["matchScore"] or 0)),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "allWithPending"}, indent=1)[:3000])


if __name__ == "__main__":
    main()
