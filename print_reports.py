import sqlite3
import json

db_path = r"d:\1 - Projects\Projects\CareerOS\CareerOS\apps\api\data\career_os.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("SELECT id, payload FROM entities WHERE entity_type='aa_pre_submit_report';")
reports = c.fetchall()
for r in reports:
    print(f"\nReport ID: {r[0]}")
    try:
        p = json.loads(r[1])
        print(json.dumps(p, indent=2))
    except Exception as e:
        print("Raw:", r[1])

conn.close()
