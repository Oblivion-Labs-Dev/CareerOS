import sqlite3
import json

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()

cur.execute("""
    SELECT id, json_extract(payload, '$.company'), json_extract(payload, '$.title'), json_extract(payload, '$.location'), json_extract(payload, '$.status'), json_extract(payload, '$.applyUrl'), json_extract(payload, '$.priority')
    FROM entities
    WHERE entity_type = 'aa_autopilot_job'
    AND (
        lower(json_extract(payload, '$.company')) IN ('extrahopnetworks', 'extrahop', 'robinhood', 'doordashusa', 'doordash', 'anthropic', 'okta', 'coupang', 'datadog')
        OR lower(json_extract(payload, '$.location')) LIKE '%wa%'
        OR lower(json_extract(payload, '$.location')) LIKE '%seattle%'
        OR lower(json_extract(payload, '$.location')) LIKE '%bellevue%'
    )
""")
rows = cur.fetchall()
print(f"Found {len(rows)} WA / priority company jobs in entities:")
for r in rows:
    print(f"{r[0]} | {r[1]} | {r[2]} | Loc: {r[3]} | Status: {r[4]} | Prio: {r[6]} | URL: {r[5]}")

conn.close()
