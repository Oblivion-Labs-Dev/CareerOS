import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"CareerOS/apps/api")

from app.db.store import session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs

with session_scope() as db:
    all_jobs = list_autopilot_jobs(db)
    anthropic_jobs = [j for j in all_jobs if (j.get("company") or "").lower() == "anthropic"]
    print(f"Total Anthropic jobs in DB: {len(anthropic_jobs)}")
    by_status = {}
    for j in anthropic_jobs:
        st = j.get("status")
        by_status[st] = by_status.get(st, 0) + 1
    print("By status:", by_status)
    print("\nDetailed list:")
    for j in anthropic_jobs:
        title = j.get("title", "")
        st = j.get("status")
        att = j.get("attemptCount", 0)
        url = j.get("applicationUrl") or j.get("url") or ""
        sub_at = j.get("submittedAt")
        created_at = j.get("createdAt")
        err = str(j.get("lastError") or "")
        print(f"[{st}] attempts={att} | {title} | sub={sub_at} | err={err[:80]} | url={url}")
