import sqlite3
import json

conn = sqlite3.connect('data/career_os.db')
cur = conn.cursor()

cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
all_jobs = [(r[0], json.loads(r[1])) for r in cur.fetchall()]

non_us_words = [
    "argentina", "turkey", "türkiye", "india", "london", "uk", "united kingdom",
    "canada", "toronto", "vancouver", "germany", "berlin", "munich",
    "brazil", "australia", "sydney", "singapore", "ireland", "dublin",
    "japan", "tokyo", "china", "emea", "apac", "latam", "mexico",
    "netherlands", "amsterdam", "spain", "madrid", "barcelona", "sweden",
    "chile", "colombia", "poland", "warsaw", "krakow", "portugal", "lisbon",
    "italy", "france", "paris", "switzerland", "austria", "belgium", "denmark",
    "norway", "finland", "israel", "philippines", "vietnam", "taiwan", "budapest", "hungary"
]

def is_non_us(job: dict) -> bool:
    title = (job.get('title') or '').lower()
    loc = (job.get('location') or '').lower()
    desc = (job.get('description') or '')[:500].lower()
    
    for word in non_us_words:
        if f"({word})" in title or f" - {word}" in title or f", {word}" in title or f" {word}" in title:
            return True
        if word in loc:
            return True
    return False

def is_wa_seattle_bellevue(job: dict) -> bool:
    import re
    loc = (job.get('location') or '').lower()
    title = (job.get('title') or '').lower()
    text = f"{title} {loc}"
    return bool(re.search(r"\b(seattle|bellevue|redmond|kirkland|washington|wa)\b", text, re.I))


# Separate into Tier 1 (WA / Seattle / Bellevue), Tier 2 (US), and Non-US
tier1 = []
tier2 = []
non_us_count = 0

for j_id, j in all_jobs:
    if j.get('status') != 'QUEUED':
        continue
    
    # Check if non-US
    if is_non_us(j):
        j['status'] = 'INELIGIBLE'
        j['skipReason'] = "Location outside United States"
        cur.execute("UPDATE entities SET payload = ? WHERE id = ?", (json.dumps(j), j_id))
        non_us_count += 1
        continue

    # Tier 1 WA
    if is_wa_seattle_bellevue(j):
        j['priority'] = 100
        tier1.append((j_id, j))
    else:
        j['priority'] = 50
        tier2.append((j_id, j))

print(f"Marked {non_us_count} non-US jobs as INELIGIBLE.")
print(f"Tier 1 (Seattle/Bellevue/WA) Senior SWE queued: {len(tier1)}")
for j_id, j in tier1:
    print(f"  [Tier 1] {j.get('company')} | {j.get('title')} | {j.get('location')}")

print(f"\nTier 2 (United States) Senior SWE queued: {len(tier2)}")
for j_id, j in tier2[:15]:
    print(f"  [Tier 2] {j.get('company')} | {j.get('title')} | {j.get('location')}")

# Save priorities
for j_id, j in tier1 + tier2:
    cur.execute("UPDATE entities SET payload = ? WHERE id = ?", (json.dumps(j), j_id))

conn.commit()
conn.close()
print("\nQueue cleanly sanitized and prioritized for Seattle/Bellevue WA first, then US.")
