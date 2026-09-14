import sqlite3
import json
import datetime

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()
cur.execute("SELECT payload FROM entities WHERE entity_type = 'aa_autopilot_run' ORDER BY rowid DESC LIMIT 1")
row = cur.fetchone()
if row:
    run = json.loads(row[0])
    print("Active Run ID:", run.get("id"), "Status:", run.get("status"))
    print("Run stats - Submitted:", run.get("submittedCount"), "Failed:", run.get("failedCount"), "Skipped:", run.get("skippedCount"))
    print("Last Heartbeat:", run.get("lastHeartbeatAt"))
    print("Active Job:", run.get("activeJob"))

cur.execute("SELECT COUNT(*) FROM entities WHERE entity_type = 'aa_autopilot_job' AND json_extract(payload, '$.status') = 'QUEUED'")
print("Queued count:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM entities WHERE entity_type = 'aa_autopilot_job' AND json_extract(payload, '$.status') = 'SUBMITTED'")
print("Total submitted in DB:", cur.fetchone()[0])
conn.close()
