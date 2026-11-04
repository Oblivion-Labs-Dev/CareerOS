import sqlite3
import json

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()

cur.execute("SELECT payload FROM entities WHERE id = 'apjob_8a7b043e-4601-4253-9721-ce7e32ab5913'")
p = json.loads(cur.fetchone()[0])
print("Job URL:", p.get("applicationUrl") or p.get("applyUrl") or p.get("listingUrl"))

conn.close()
