import sqlite3
import json

db_path = "d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/career_os.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Get the last 10 runs
cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_run' ORDER BY rowid DESC LIMIT 10")
runs = cur.fetchall()
print(f"=== LAST {len(runs)} RUNS ===")
for rid, pl in runs:
    p = json.loads(pl)
    print(f"Run {rid}: {p.get('status')} | Started: {p.get('startedAt')} | Completed: {p.get('completedAt')} | Target: {p.get('targetProcessCount')} | Processed: {p.get('processedCount')} | Sub: {p.get('submittedCount')} | Rev: {p.get('needsReviewCount')} | Fail: {p.get('failedCount')}")

# Get all jobs associated with the most recent runs (e.g. today's runs)
cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job' ORDER BY rowid DESC LIMIT 40")
recent_jobs = cur.fetchall()
print(f"\n=== RECENT 40 JOBS ===")
for jid, pl in recent_jobs:
    p = json.loads(pl)
    st = p.get('status')
    comp = p.get('company') or p.get('companyName')
    title = p.get('title') or p.get('jobTitle')
    rid = p.get('lastAttemptRunId')
    skip = p.get('skipReason')
    fail = p.get('failureReason')
    rec = p.get('submissionReceipt')
    print(f"[{st:12}] {jid} | {comp} - {title} | Run: {rid}")
    if rec:
        print(f"    Receipt: {rec}")
    if skip:
        print(f"    SkipReason: {skip[:120]}")
    if fail:
        print(f"    FailReason: {fail[:120]}")

conn.close()
