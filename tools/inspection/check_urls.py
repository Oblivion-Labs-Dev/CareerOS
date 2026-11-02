import sqlite3
import json

conn = sqlite3.connect("apps/api/data/career_os.db")
cursor = conn.cursor()
rows = cursor.execute("SELECT payload FROM entities WHERE entity_type='aa_discovered_job' LIMIT 20").fetchall()
for i, r in enumerate(rows):
    data = json.loads(r[0])
    app_url = data.get('applicationUrl')
    list_url = data.get('listingUrl')
    company = data.get('company')
    title = data.get('title')
    print(f"[{company}] {title}")
    print(f"  applicationUrl: {app_url}")
    print(f"  listingUrl: {list_url}")
