import sqlite3
import json

conn = sqlite3.connect("apps/api/data/career_os.db")
cursor = conn.cursor()
rows = cursor.execute("SELECT payload FROM entities WHERE entity_type='aa_discovered_job' LIMIT 3").fetchall()
for r in rows:
    print(r[0])
    print("=" * 40)
