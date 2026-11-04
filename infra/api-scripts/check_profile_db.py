import sqlite3
import json

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()

cur.execute("SELECT payload FROM entities WHERE id = 'profile'")
row = cur.fetchone()
if row:
    p = json.loads(row[0])
    print("Work Auth:", p.get("workAuth"))
    print("Visa:", p.get("visa"))
    print("Ethnicity:", p.get("ethnicity"), p.get("race"))
    print("Location:", p.get("location"), p.get("city"), p.get("state"))

conn.close()
