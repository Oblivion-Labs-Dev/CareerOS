import sqlite3
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

db_path = Path("CareerOS/apps/api/data/career_os.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# 1. Active / latest runs
print("=== ACTIVE / LATEST RUNS ===")
cur.execute("SELECT id, payload FROM entities WHERE entity_type='aa_autopilot_run' ORDER BY rowid DESC LIMIT 2")
for rid, p_str in cur.fetchall():
    p = json.loads(p_str)
    print(f"Run {rid}: status={p.get('status')}, processed={p.get('processedCount')}/{p.get('targetProcessCount')}, submitted={p.get('submittedCount')}, staged={p.get('stagedCount')}, heartbeat={p.get('lastHeartbeatAt')}, selfHealing={p.get('settings', {}).get('selfHealing')}")

# 2. Applying / Recent jobs
print("\n=== APPLYING JOBS ===")
cur.execute("SELECT id, payload FROM entities WHERE entity_type='aa_autopilot_job' AND json_extract(payload, '$.status')='APPLYING'")
applying = cur.fetchall()
print(f"Total APPLYING: {len(applying)}")
for jid, p_str in applying:
    p = json.loads(p_str)
    print(f"  [{jid}] {p.get('company')} - {p.get('title')}")
    print(f"  Step: {p.get('currentStep')}, updated: {p.get('updatedAt')}")
    for cp in (p.get('checkpointHistory') or [])[-3:]:
        print(f"    - {cp.get('step')}: {cp.get('details')}")

# 3. Queue counts
print("\n=== JOB STATUS COUNTS ===")
cur.execute("SELECT json_extract(payload, '$.status'), count(*) FROM entities WHERE entity_type='aa_autopilot_job' GROUP BY 1 ORDER BY 2 DESC")
for st, cnt in cur.fetchall():
    print(f"  {st}: {cnt}")

# 4. Latest updated jobs (last 5)
print("\n=== LAST 5 UPDATED JOBS ===")
cur.execute("SELECT id, payload FROM entities WHERE entity_type='aa_autopilot_job' ORDER BY json_extract(payload, '$.updatedAt') DESC LIMIT 5")
for jid, p_str in cur.fetchall():
    p = json.loads(p_str)
    print(f"  [{p.get('status')}] {p.get('company')} - {p.get('title')} ({p.get('updatedAt')})")
    if p.get('status') in ('NEEDS_REVIEW', 'FAILED') and p.get('lastError'):
        print(f"    Error: {p.get('lastError')[:120]}")
    if p.get('status') == 'SUBMITTED':
        print(f"    Submitted: {p.get('submittedAt')}")
