import sqlite3
import json

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()

cur.execute("""
    SELECT id, json_extract(payload, '$.company'), json_extract(payload, '$.title'), json_extract(payload, '$.applyUrl'), json_extract(payload, '$.lastError')
    FROM entities
    WHERE entity_type = 'aa_autopilot_job' AND json_extract(payload, '$.status') = 'FAILED'
    ORDER BY json_extract(payload, '$.updatedAt') DESC
    LIMIT 10
""")
for r in cur.fetchall():
    print(f"{r[0]} | {r[1]} | {r[2]}")
    print(f"  URL: {r[3]}")
    print(f"  Error: {r[4]}")

conn.close()
