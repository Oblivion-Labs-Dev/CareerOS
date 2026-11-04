import sqlite3
import json

db_path = "d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/career_os.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("""
    SELECT id, payload FROM entities 
    WHERE entity_type = 'aa_autopilot_job'
""")

all_jobs = []
for r in cur.fetchall():
    p = json.loads(r[1])
    all_jobs.append((r[0], p))

# Group by status
status_counts = {}
runs = {}
for jid, p in all_jobs:
    st = p.get('status')
    status_counts[st] = status_counts.get(st, 0) + 1
    rid = p.get('lastAttemptRunId')
    if rid:
        if rid not in runs:
            runs[rid] = []
        runs[rid].append((jid, p))

print("Overall Status Counts:", status_counts)
print(f"\nTotal runs with associated jobs: {len(runs)}")

# Examine recent runs
for rid, jobs in list(runs.items())[:5]:
    print(f"\n================ Run: {rid} (Jobs: {len(jobs)}) ================")
    for jid, p in jobs:
        st = p.get('status')
        comp = p.get('company') or p.get('companyName')
        title = p.get('title') or p.get('jobTitle')
        receipt = p.get('submissionReceipt') or p.get('receiptId')
        skip = p.get('skipReason')
        fail = p.get('failureReason')
        print(f"[{st}] {comp} - {title} ({jid})")
        if receipt: print(f"   Receipt: {receipt}")
        if skip: print(f"   Skip: {skip}")
        if fail: print(f"   Fail: {fail}")
        if p.get('validationIssues'): print(f"   ValIssues: {p.get('validationIssues')}")

conn.close()
