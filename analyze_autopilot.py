import sqlite3
import json

db_path = r"d:\1 - Projects\Projects\CareerOS\CareerOS\apps\api\data\career_os.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("SELECT id, entity_type, payload FROM entities WHERE entity_type='aa_autopilot_job';")
rows = c.fetchall()
print(f"Total Autopilot Jobs: {len(rows)}")
for r in rows:
    p = json.loads(r[2])
    print(f"\nID: {r[0]}")
    print(f"  Company: {p.get('company')}, Title: {p.get('title')}")
    print(f"  Status: {p.get('status')}, State: {p.get('state')}")
    print(f"  URL: {p.get('jobUrl') or p.get('applicationUrl')}")
    print(f"  Failure Reason: {p.get('failureReason') or p.get('error') or p.get('errorMessage')}")
    print(f"  Log / Details: {p.get('failureTaxonomy') or p.get('details') or p.get('lastError')}")

c.execute("SELECT id, payload FROM entities WHERE entity_type='aa_pre_submit_report';")
reports = c.fetchall()
print(f"\nTotal Pre-Submit Reports: {len(reports)}")
for r in reports:
    p = json.loads(r[1])
    print(f"Report ID: {r[0]} | App ID: {p.get('applicationId')} | Passed: {p.get('passed')} | Blockers: {p.get('blockers')} | Issues: {p.get('issues')}")

conn.close()
