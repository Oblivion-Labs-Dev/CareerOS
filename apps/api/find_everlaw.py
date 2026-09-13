import sqlite3
import json

db_path = "d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/career_os.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job' AND payload LIKE '%Everlaw%'")
for r in cur.fetchall():
    p = json.loads(r[1])
    print(r[0], p.get("status"), p.get("lastError"))

conn.close()
