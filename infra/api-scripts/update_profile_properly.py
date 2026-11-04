import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope, get_kv, set_kv
from scripts.fix_all_profiles import PROFILE_DATA

with session_scope() as db:
    existing = get_kv(db, "profile") or {}
    merged = {**existing, **PROFILE_DATA}
    set_kv(db, "profile", merged)
    print("set_kv executed successfully.")

with session_scope() as db:
    p = get_kv(db, "profile")
    print("Read back:")
    print("  First name:", p.get("firstName"))
    print("  City:", p.get("city"))
    print("  State:", p.get("state"))
    print("  Work auth:", p.get("workAuth"))
    print("  Ethnicity:", p.get("race"), p.get("ethnicity"))
