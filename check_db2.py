import sqlite3
conn = sqlite3.connect('data/career_os.db')
# Check tables
tables = conn.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall()
print("Tables:", [t[0] for t in tables])

# Check entities table
if any(t[0] == 'entities' for t in tables):
    count = conn.execute('SELECT COUNT(*) FROM entities WHERE entity_type="aa_autopilot_job"').fetchone()[0]
    print(f"Autopilot jobs count: {count}")
    
    # Get some sample jobs
    rows = conn.execute('SELECT payload FROM entities WHERE entity_type="aa_autopilot_job" LIMIT 5').fetchall()
    for r in rows:
        import json
        job = json.loads(r[0])
        print(f"  {job.get('company')} - {job.get('title')} - {job.get('status')} - Match: {job.get('matchScore')}")
else:
    print("No entities table")