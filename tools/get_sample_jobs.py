import sqlite3
import json

conn = sqlite3.connect("apps/api/data/career_os.db")
cursor = conn.cursor()
rows = cursor.execute("SELECT id, payload FROM entities WHERE entity_type='aa_discovered_job' LIMIT 500").fetchall()

by_company = {}
for row_id, payload_str in rows:
    try:
        data = json.loads(payload_str)
        company = data.get("company", "").strip()
        url = data.get("url", "").strip()
        title = data.get("title", "").strip()
        job_id = data.get("id") or row_id
        if company and url and company.lower() not in by_company:
            by_company[company.lower()] = {
                "id": job_id,
                "company": company,
                "title": title,
                "url": url,
                "platform": data.get("platform", "unknown")
            }
    except Exception as e:
        continue

print(f"Total distinct companies found: {len(by_company)}")
sample = list(by_company.values())[:15]
print(json.dumps(sample, indent=2))
