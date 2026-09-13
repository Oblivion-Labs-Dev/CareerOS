import sqlite3, json

conn = sqlite3.connect('data/career_os.db')
cur = conn.cursor()

cur.execute("""
SELECT json_extract(payload, '$.status'), count(*)
FROM entities
WHERE entity_type = 'aa_application_attempt'
GROUP BY json_extract(payload, '$.status')
""")
print("Attempts by status:", dict(cur.fetchall()))

cur.execute("""
SELECT json_extract(payload, '$.status'), count(*)
FROM entities
WHERE entity_type = 'aa_autopilot_job'
GROUP BY json_extract(payload, '$.status')
""")
print("Queue jobs by status:", dict(cur.fetchall()))

cur.execute("""
SELECT count(*)
FROM entities
WHERE entity_type = 'aa_autopilot_job'
  AND json_extract(payload, '$.status') IN ('QUEUED', 'RETRYING', 'queued', 'retrying')
""")
print("Active pending queue count:", cur.fetchone()[0])

cur.execute("""
SELECT json_extract(payload, '$.id'), json_extract(payload, '$.status'), length(payload)
FROM entities
WHERE entity_type = 'aa_autopilot_run'
ORDER BY rowid DESC LIMIT 5
""")
for r in cur.fetchall():
    print("Run:", r)

cur.execute("""
SELECT json_extract(payload, '$.company'), json_extract(payload, '$.title'), json_extract(payload, '$.currentStep'), json_extract(payload, '$.applicationUrl')
FROM entities
WHERE entity_type='aa_autopilot_job' AND json_extract(payload, '$.status')='APPLYING'
""")
for r in cur.fetchall():
    print("  -> ACTIVE JOB:", r[0], "-", r[1], "| Step:", r[2])
conn.close()

import sys, time
sys.path.insert(0, '.')
from app.db.store import session_scope
from app.services.application_assistant.autopilot_runner import AutopilotRunner

t0 = time.time()
with session_scope() as db:
    runner = AutopilotRunner.get_instance()
    st = runner.get_status(db)
t1 = time.time()
print(f"runner.get_status(db) took {t1 - t0:.3f}s. Running: {st.get('running')}, Queue: {st.get('queueSize')}")

conn = sqlite3.connect('data/career_os.db')
cur = conn.cursor()
cur.execute("""
SELECT payload FROM entities WHERE entity_type='aa_autopilot_job' AND json_extract(payload, '$.company') LIKE '%Tebra%'
""")
r = cur.fetchone()
if r:
    import json
    j = json.loads(r[0])
    print("Tebra:", j.get('status'), "| Step:", j.get('currentStep'), "| Last Error:", j.get('lastError'))
conn.close()
