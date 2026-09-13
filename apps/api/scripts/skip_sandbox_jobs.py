import sqlite3, json
from pathlib import Path

conn = sqlite3.connect("CareerOS/apps/api/data/career_os.db")
cur = conn.cursor()
cur.execute("""
    SELECT id, json_extract(payload, '$.company'), json_extract(payload, '$.title'), json_extract(payload, '$.applicationUrl')
    FROM entities
    WHERE entity_type='aa_autopilot_job' AND json_extract(payload, '$.company') LIKE '%Examplecorp%'
""")
rows = cur.fetchall()
for r in rows:
    print(r)
    # mark as SKIPPED
    cur.execute("UPDATE entities SET payload=json_set(payload, '$.status', 'SKIPPED', '$.skipReason', 'Sandbox mock board') WHERE id=?", (r[0],))
conn.commit()
print(f"Skipped {len(rows)} Examplecorp sandbox jobs.")
