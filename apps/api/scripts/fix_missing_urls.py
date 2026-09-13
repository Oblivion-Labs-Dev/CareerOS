import sqlite3
import json
from pathlib import Path

db_path = Path("CareerOS/apps/api/data/career_os.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("""
    SELECT id, payload FROM entities WHERE entity_type='aa_autopilot_job'
""")
missing_app_url = 0
fixed = 0
for row in cur.fetchall():
    p = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    app_url = p.get("applicationUrl")
    other_url = p.get("applyUrl") or p.get("listingUrl") or p.get("jobUrl")
    if not app_url and other_url:
        missing_app_url += 1
        p["applicationUrl"] = other_url
        cur.execute("UPDATE entities SET payload=? WHERE id=?", (json.dumps(p), row[0]))
        fixed += 1

conn.commit()
print(f"Total jobs missing applicationUrl fixed: {fixed}")
