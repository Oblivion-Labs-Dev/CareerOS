import sqlite3
import json

conn = sqlite3.connect("apps/api/data/career_os.db")
cursor = conn.cursor()
rows = cursor.execute("SELECT payload FROM entities WHERE entity_type='aa_discovered_job' LIMIT 10").fetchall()
for i, r in enumerate(rows):
    data = json.loads(r[0])
    print(f"Job {i}: keys={list(data.keys())}")
    print(f"  company: {data.get('company') or data.get('company_name') or data.get('employer')}")
    print(f"  title: {data.get('title') or data.get('role_title') or data.get('role')}")
    print(f"  url: {data.get('apply_url') or data.get('url') or data.get('job_url') or data.get('link')}")
