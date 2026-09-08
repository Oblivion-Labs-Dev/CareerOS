import os
import json
import sqlite3

db_path = os.path.join(os.path.dirname(__file__), "..", "data", "career_os.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Get recent autopilot jobs
cur.execute("SELECT id, payload FROM entities WHERE entity_type='autopilot_job' ORDER BY id DESC LIMIT 20")
rows = cur.fetchall()
print(f"Total autopilot jobs queried: {len(rows)}")

confirmed = []
for row_id, payload_str in rows:
    try:
        data = json.loads(payload_str)
        status = data.get("status")
        title = data.get("job_title") or data.get("target_title")
        company = data.get("company_name") or data.get("company")
        receipt = data.get("confirmation_receipt_id")
        created = data.get("created_at")
        updated = data.get("updated_at")
        ext_conf = data.get("external_confirmation") or {}
        print(f"Job {row_id} | {company} - {title} | Status: {status} | Receipt: {receipt}")
        if status == "SUBMITTED" or receipt:
            confirmed.append((row_id, company, title, receipt, ext_conf))
    except Exception as e:
        print(f"Error parsing {row_id}: {e}")

print(f"\n--- Confirmed / Submitted count in last 20: {len(confirmed)} ---")
conn.close()
