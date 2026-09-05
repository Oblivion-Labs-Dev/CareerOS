import sqlite3
import json

conn = sqlite3.connect("apps/api/data/career_os.db")
cursor = conn.cursor()
rows = cursor.execute("SELECT payload FROM entities WHERE entity_type='aa_discovered_job'").fetchall()

selected = {}
for r in rows:
    try:
        data = json.loads(r[0])
        company = data.get("company") or ""
        title = data.get("title") or ""
        url = data.get("applicationUrl") or data.get("listingUrl") or ""
        
        # We want distinct companies with active URLs
        if company and url and "greenhouse.io" in url:
            c_norm = company.strip().lower()
            if c_norm not in selected and len(selected) < 10:
                selected[c_norm] = {
                    "id": data.get("id"),
                    "company": company.strip(),
                    "title": title.strip(),
                    "applicationUrl": url.strip(),
                    "location": data.get("location", ""),
                }
    except Exception:
        continue

print(f"Selected {len(selected)} jobs from distinct companies:")
for i, j in enumerate(selected.values(), 1):
    print(f"{i}. [{j['company']}] {j['title']} -> {j['applicationUrl']}")
