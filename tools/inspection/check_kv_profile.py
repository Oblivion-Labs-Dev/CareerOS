import sqlite3
import json

conn = sqlite3.connect("apps/api/data/career_os.db")
cursor = conn.cursor()
rows = cursor.execute("SELECT key, value FROM kv_store WHERE key IN ('documents', 'profile', 'user_profile', 'candidate_profile')").fetchall()
for k, v in rows:
    print(f"Key: {k}")
    try:
        data = json.loads(v)
        if isinstance(data, dict):
            for subk, subv in data.items():
                if isinstance(subv, (str, int, float, bool)):
                    print(f"  {subk}: {subv}")
                elif isinstance(subv, dict):
                    print(f"  {subk}: {list(subv.keys())}")
                else:
                    print(f"  {subk}: {type(subv)}")
        else:
            print(f"  Value: {data}")
    except Exception:
        print(f"  Raw: {v[:200]}")
