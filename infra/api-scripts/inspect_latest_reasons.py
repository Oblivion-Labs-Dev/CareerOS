import sqlite3
import json

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()

cur.execute("""
    SELECT id, json_extract(payload, '$.company'), json_extract(payload, '$.title'), json_extract(payload, '$.status'), json_extract(payload, '$.reviewReason'), json_extract(payload, '$.lastError'), payload
    FROM entities
    WHERE entity_type = 'aa_autopilot_job'
    ORDER BY json_extract(payload, '$.updatedAt') DESC
    LIMIT 6
""")
for r_id, comp, title, status, reason, err, p_str in cur.fetchall():
    print(f"=== {r_id} | {comp} | {title} | {status} ===")
    print("Reason:", reason)
    print("Error:", err)
    p = json.loads(p_str)
    sub = p.get("submissionEvidence") or {}
    dom_v = sub.get("domVerification") or {}
    issues = dom_v.get("issues") or []
    if issues:
        print("DOM Issues:")
        for iss in issues:
            print("  *", iss)
    print()

conn.close()
