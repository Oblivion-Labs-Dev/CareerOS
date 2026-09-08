import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope
from app.services.application_assistant.persistence import get_active_autopilot_run

def main():
    with session_scope() as db:
        run = get_active_autopilot_run(db)
        if not run:
            print("No active autopilot run found.")
            return
        print("Run ID:", run.get("id"))
        print("Status:", run.get("status"))
        print("Processed:", run.get("processedCount"), "Submitted:", run.get("submittedCount"), "Staged:", run.get("stagedCount"), "Failed:", run.get("failedCount"))
        print("Total Logs count:", len(run.get("logs") or []))
        print("\nAll recent logs:")
        for log in (run.get("logs") or [])[-30:]:
            msg = log.get("message", "")
            ts = log.get("timestamp", "")
            lvl = log.get("level", "")
            print(f"[{ts}] [{lvl}] {msg}".encode("ascii", errors="replace").decode("ascii"))

if __name__ == "__main__":
    main()
