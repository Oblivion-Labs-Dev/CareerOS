import sqlite3
import glob
import json
import os

dbs = glob.glob("**/career_os.db", recursive=True) + glob.glob("apps/api/data/**/*.db", recursive=True) + glob.glob("../**/career_os.db", recursive=True)
dbs = list(set(dbs))
print("Found databases:", dbs)

for db_path in dbs:
    print("\n" + "="*50)
    print(f"DATABASE: {db_path}")
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in c.fetchall()]
        print("Tables:", tables)

        if "entities" in tables:
            c.execute("SELECT entity_type, count(*) FROM entities GROUP BY entity_type;")
            print("Entity counts:", c.fetchall())

            c.execute("SELECT entity_type, entity_id, data FROM entities WHERE entity_type IN ('aa_application_draft', 'aa_discovered_job', 'job', 'application', 'failure_event', 'error_log') OR data LIKE '%fail%' OR data LIKE '%error%' LIMIT 20;")
            rows = c.fetchall()
            print(f"Matching rows count: {len(rows)}")
            for r in rows:
                print(f"\n--- Entity Type: {r[0]} | ID: {r[1]} ---")
                try:
                    parsed = json.loads(r[2])
                    print(json.dumps(parsed, indent=2)[:500])
                except Exception:
                    print(str(r[2])[:500])
        conn.close()
    except Exception as exc:
        print(f"Error inspecting {db_path}: {exc}")
