import sqlite3
import json

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()

cur.execute("""
    SELECT id, json_extract(payload, '$.company'), json_extract(payload, '$.title'), json_extract(payload, '$.matchScore'), json_extract(payload, '$.scoringReason'), json_extract(payload, '$.status'), payload
    FROM entities
    WHERE id LIKE 'apjob_%'
    ORDER BY json_extract(payload, '$.updatedAt') DESC
    LIMIT 10
""")
for r in cur.fetchall():
    p = json.loads(r[6])
    print(f"{r[0]} | {r[1]} | {r[2]} | Score: {r[3]} | Status: {r[5]}")
    print("  Match Score:", p.get("matchScore"))
    print("  Scoring Reason:", p.get("scoringReason"))
    print("  Review Reason:", p.get("reviewReason"))
    print("  Last Error:", p.get("lastError"))
    print("  MinMatchScore setting:", p.get("minMatchScore"))

conn.close()
