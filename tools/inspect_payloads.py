import sqlite3
import json

conn = sqlite3.connect("apps/api/data/career_os.db")
cursor = conn.cursor()
rows = cursor.execute("SELECT entity_type, payload FROM entities LIMIT 5").fetchall()
for etype, p in rows:
    print(f"Type: {etype}")
    print(p[:300])
    print("-" * 40)
