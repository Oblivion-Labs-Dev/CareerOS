import sqlite3
import json
import datetime

db_path = "d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/career_os.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

now = datetime.datetime.now(datetime.timezone.utc)
twelve_hours_ago = (now - datetime.timedelta(hours=12)).isoformat()
print(f"Current time (UTC): {now.isoformat()}")
print(f"12 hours ago (UTC): {twelve_hours_ago}")

# Check autopilot runs in last 12 hours
print("\n=== AUTOPILOT RUNS IN LAST 12 HOURS ===")
cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_run' ORDER BY rowid DESC")
runs_12h = []
for r in cur.fetchall():
    p = json.loads(r[1])
    started = p.get('startedAt') or ''
    if started >= twelve_hours_ago:
        runs_12h.append((r[0], p))
        print(f"Run {r[0]}: status={p.get('status')}, target={p.get('targetProcessCount')}, processed={p.get('processedCount')}, submitted={p.get('submittedCount')}, needs_review={p.get('needsReviewCount')}, failed={p.get('failedCount')}")
        print(f"  started={p.get('startedAt')}, completed={p.get('completedAt')}")
        print(f"  settings={p.get('settings')}")

# Check all jobs updated or attempted in last 12 hours
print("\n=== JOBS TOUCHED IN LAST 12 HOURS ===")
cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
jobs_12h = []
for r in cur.fetchall():
    p = json.loads(r[1])
    ts = p.get('updatedAt') or p.get('queuedAt') or p.get('claimedAt') or ''
    last_att = p.get('lastAttemptAt') or ''
    if ts >= twelve_hours_ago or last_att >= twelve_hours_ago:
        jobs_12h.append((r[0], p))

print(f"Total jobs touched in last 12 hours: {len(jobs_12h)}")
for jid, p in jobs_12h:
    comp = p.get('company') or p.get('companyName')
    title = p.get('title') or p.get('jobTitle')
    status = p.get('status')
    receipt = p.get('submissionReceipt') or p.get('receiptId')
    app_url = p.get('applicationUrl') or p.get('url')
    run_id = p.get('lastAttemptRunId')
    print(f"\n--- [{status}] {jid} ---")
    print(f"  Company/Title: {comp} - {title}")
    print(f"  URL: {app_url}")
    print(f"  Run ID: {run_id}")
    print(f"  Receipt: {receipt}")
    if p.get('failureReason'):
        print(f"  Failure/Review: {p.get('failureReason')}")
    if p.get('skipReason'):
        print(f"  Skip Reason: {p.get('skipReason')}")
    if p.get('formState'):
        fs = p.get('formState')
        print(f"  FormState Fields Count: {len(fs.get('fields', [])) if isinstance(fs, dict) else 'N/A'}")
    if p.get('answers'):
        print(f"  Answers Count: {len(p.get('answers', {}))}")
    if p.get('validationIssues'):
        print(f"  Validation Issues: {p.get('validationIssues')}")

conn.close()
