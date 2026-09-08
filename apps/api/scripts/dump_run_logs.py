import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope
from app.services.application_assistant.persistence import get_active_autopilot_run

with session_scope() as db:
    run = get_active_autopilot_run(db)
    if not run:
        print("No active run")
        exit(0)

    logs = run.get("logs") or []
    print(f"Total logs in active run: {len(logs)}")
    print("\n--- Last 20 logs in run payload ---")
    for l in logs[-20:]:
        ts = l.get("timestamp", "")
        lvl = l.get("level", "")
        msg = l.get("message", "")
        print(f"[{ts}] [{lvl}] {msg}".encode("ascii", errors="replace").decode("ascii"))
