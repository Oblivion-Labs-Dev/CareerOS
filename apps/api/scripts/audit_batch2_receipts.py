import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import get_kv, session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs

with session_scope() as db:
    receipts_store = get_kv(db, "autopilot_submission_receipts") or {}
    jobs = list_autopilot_jobs(db)
    jobs_map = {j["id"]: j for j in jobs}

    batch2_job_ids = [
        "apjob_248a9323-ab0a-4948-9355-4b77ee3efab3",
        "apjob_1942af97",
        "apjob_68e26d6b",
        "apjob_2b1ee69e",
        "apjob_f965d82f",
        "apjob_bc2a9425",
        "apjob_a6bf8033",
        "apjob_e23b128e",
        "apjob_1e680cf0",
        "apjob_6a251eda",
    ]

    print("=== BATCH 2 CONFIRMED APPLICATIONS AUDIT ===")
    for idx, jid in enumerate(batch2_job_ids, 1):
        job = jobs_map.get(jid, {})
        rcpt = receipts_store.get(jid, {})
        title = rcpt.get("title") or job.get("title")
        company = rcpt.get("company") or job.get("company")
        status = job.get("status")
        rcpt_id = rcpt.get("receiptId")
        conf_url = rcpt.get("confirmationUrl")
        ts = rcpt.get("submittedAt") or job.get("updatedAt")
        print(f"| **{idx}** | **{company}** | {title} | `{rcpt_id}` | [{company} Confirmation]({conf_url}) | `{ts}` |")
