import sqlite3
conn = sqlite3.connect('data/career_os.db')
cur = conn.cursor()
cur.execute("SELECT id, json_extract(payload,'$.company'), json_extract(payload,'$.title'), json_extract(payload,'$.status') FROM entities WHERE entity_type='aa_autopilot_job' AND json_extract(payload,'$.status')='APPLYING'")
rows = cur.fetchall()
for r in rows:
    print('IN_FLIGHT:', r)
if not rows:
    print('No in-flight jobs')