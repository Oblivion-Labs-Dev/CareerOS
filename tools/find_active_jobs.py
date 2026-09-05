import sqlite3
import json

conn = sqlite3.connect('apps/api/data/career_os.db')
c = conn.cursor()
c.execute("SELECT payload FROM entities WHERE entity_type = 'job'")
rows = c.fetchall()

seen = set()
count = 0
for r in rows:
    try:
        data = json.loads(r[0])
        url = data.get('applicationUrl') or data.get('url') or ''
        company = data.get('company') or ''
        title = data.get('title') or ''
        if 'greenhouse.io' in url and company and company not in seen:
            seen.add(company)
            print(f"{company} | {title} | {url}")
            count += 1
            if count >= 15:
                break
    except Exception as ex:
        pass
