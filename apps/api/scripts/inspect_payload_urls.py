import sqlite3
import json

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()

cur.execute("SELECT payload FROM entities WHERE id = 'apjob_979c8e05-b894-4110-b3e0-6c4192407e71'")
row = cur.fetchone()
if row:
    p = json.loads(row[0])
    print("Keys in payload:", list(p.keys()))
    print("URLs:", {k: v for k, v in p.items() if "url" in k.lower() or "link" in k.lower() or "id" in k.lower()})

conn.close()
