import sqlite3
import json

db_path = r"d:\1 - Projects\Projects\CareerOS\CareerOS\apps\api\data\career_os.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

print("--- RECENT BROWSER RUNS ---")
c.execute("SELECT id, entity_type, payload FROM entities WHERE entity_type='aa_browser_run' ORDER BY rowid DESC LIMIT 10;")
for row in c.fetchall():
    print(f"ID: {row[0]}")
    try:
        p = json.loads(row[2])
        print(f"Status: {p.get('status')}, Error: {p.get('error') or p.get('errorMessage')}, URL: {p.get('url') or p.get('jobUrl')}")
        print(f"Summary: {json.dumps(p, indent=2)[:400]}")
    except Exception as e:
        print("Raw payload:", row[2][:300])

print("\n--- RECENT APPLICATION DRAFTS ---")
c.execute("SELECT id, entity_type, payload FROM entities WHERE entity_type='aa_application_draft' ORDER BY rowid DESC LIMIT 10;")
for row in c.fetchall():
    print(f"\nDraft ID: {row[0]}")
    try:
        p = json.loads(row[2])
        print(f"Company: {p.get('company')}, Title: {p.get('title') or p.get('jobTitle')}, Status: {p.get('status')}")
        print(f"URL: {p.get('jobUrl') or p.get('applicationUrl')}")
        print(f"Error / Blocker: {p.get('error') or p.get('blocker') or p.get('lastError')}")
        print(f"Failure / Reason: {p.get('failureReason') or p.get('reason')}")
        print(f"Fields Count: {len(p.get('fields', []))}")
        # Print first few fields
        for f in p.get('fields', [])[:5]:
            print(f"  Field: {f.get('label')} ({f.get('normalizedKey')}) -> classification: {f.get('classification')}, proposed: {f.get('proposedValue')}")
    except Exception as e:
        print("Raw payload:", row[2][:300])

print("\n--- RECENT AUTOPILOT JOBS / RUNS ---")
c.execute("SELECT id, entity_type, payload FROM entities WHERE entity_type IN ('aa_autopilot_job', 'aa_autopilot_run') ORDER BY rowid DESC LIMIT 10;")
for row in c.fetchall():
    print(f"ID: {row[0]} ({row[1]})")
    try:
        p = json.loads(row[2])
        print(f"Status: {p.get('status')}, Failure/Error: {p.get('error') or p.get('failureReason') or p.get('errorMessage')}")
        print(f"URL: {p.get('url') or p.get('jobUrl')}")
    except Exception:
        print("Raw:", row[2][:200])

conn.close()
