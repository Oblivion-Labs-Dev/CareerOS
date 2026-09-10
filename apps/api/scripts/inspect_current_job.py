import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope
from app.services.application_assistant.persistence import get_autopilot_job

import json
with session_scope() as db:
    from app.db.store import Entity
    rows = db.query(Entity).filter(Entity.entity_type == "aa_autopilot_job").order_by(Entity.updated_at.desc()).limit(5).all()
    for row in rows:
        job = json.loads(row.payload)
        print("=" * 60)
        print("Job ID:", job.get("id"), "|", job.get("company"), "|", job.get("title"))
        print("Status:", job.get("status"), "| Updated:", job.get("updatedAt"))
        print("Last Error:", job.get("lastError"))
        sub = job.get("submissionEvidence") or {}
        dom = sub.get("domVerification") or {}
        if dom.get("issues"):
            print("Issues:")
            for iss in dom["issues"]:
                print("  *", iss.get("issueType"), "|", iss.get("label"), "| details:", iss.get("details"))
        print("DOM Values sample:", {k: v for k, v in list(dom.get("domValues", {}).items())[:8]})
