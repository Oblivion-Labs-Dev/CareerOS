import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope, get_kv

with session_scope() as db:
    p = get_kv(db, "profile") or {}
    print("Work Auth:", p.get("workAuth"))
    print("Requires sponsorship:", (p.get("workAuth") or {}).get("requiresSponsorshipNowOrFuture"))
    print("Ethnicity:", p.get("ethnicity"), p.get("race"))
    print("Location:", p.get("location"), p.get("city"), p.get("state"))
