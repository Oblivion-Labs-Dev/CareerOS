import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope
from app.services.application_assistant.persistence import get_autopilot_job

with session_scope() as db:
    job = get_autopilot_job(db, "apjob_248a9323-ab0a-4948-9355-4b77ee3efab3")
    if job:
        print("Job ID:", job.get("id"))
        print("Company:", job.get("company"))
        print("Title:", job.get("title"))
        print("Status:", job.get("status"))
        print("Updated:", job.get("updatedAt"))
        print("Last Error:", job.get("lastError"))
        print("Apply URL:", job.get("applyUrl"))
    else:
        print("Job not found")
