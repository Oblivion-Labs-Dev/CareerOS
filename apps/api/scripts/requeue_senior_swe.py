import sqlite3
import json

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()

# Reset NEEDS_REVIEW and FAILED jobs for Senior SWE to QUEUED so they can process with fixes
cur.execute("""
    SELECT id, payload FROM entities 
    WHERE entity_type = 'aa_autopilot_job' 
    AND json_extract(payload, '$.status') IN ('NEEDS_REVIEW', 'FAILED', 'QUEUED')
""")
rows = cur.fetchall()

requeued_count = 0
for r_id, p_str in rows:
    j = json.loads(p_str)
    # Ensure title is Senior SWE
    title = (j.get('title') or '').lower()
    if 'senior' not in title and 'sr.' not in title and 'sr ' not in title:
        continue
    
    # Ensure location is US / WA
    loc = (j.get('location') or '').lower()
    if any(c in loc for c in ['argentina', 'turkey', 'india', 'london', 'uk', 'germany', 'canada', 'brazil', 'budapest']):
        continue
        
    j['status'] = 'QUEUED'
    j['lastError'] = None
    j['reviewReason'] = None
    j['lockedBy'] = None
    j['lockedAt'] = None
    j['lockExpiresAt'] = None
    
    cur.execute("UPDATE entities SET payload = ? WHERE id = ?", (json.dumps(j), r_id))
    requeued_count += 1

conn.commit()

# Count available queued jobs by priority
cur.execute("""
    SELECT json_extract(payload, '$.priority'), COUNT(*) 
    FROM entities 
    WHERE entity_type = 'aa_autopilot_job' AND json_extract(payload, '$.status') = 'QUEUED'
    GROUP BY json_extract(payload, '$.priority')
""")
print("Queued jobs by priority:")
for prio, count in cur.fetchall():
    print(f"  Priority {prio}: {count} jobs")

# List top 10 queued
cur.execute("""
    SELECT id, json_extract(payload, '$.company'), json_extract(payload, '$.title'), json_extract(payload, '$.location'), json_extract(payload, '$.priority')
    FROM entities 
    WHERE entity_type = 'aa_autopilot_job' AND json_extract(payload, '$.status') = 'QUEUED'
    ORDER BY json_extract(payload, '$.priority') DESC, json_extract(payload, '$.createdAt') ASC
    LIMIT 10
""")
print("\nTop 10 queued jobs ready to run:")
for r in cur.fetchall():
    print(f"  [{r[4]}] {r[1]} | {r[2]} | {r[3]} (ID: {r[0]})")

conn.close()
print(f"\nRequeued {requeued_count} Senior SWE jobs successfully.")
