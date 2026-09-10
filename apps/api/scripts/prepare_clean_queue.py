import sqlite3
import json

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()

# Get all autopilot jobs
cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
rows = cur.fetchall()

print(f"Total autopilot jobs in DB: {len(rows)}")

# Exclude list for companies / international
INTERNATIONAL_TERMS = ["london", "uk", "germany", "berlin", "canada", "toronto", "vancouver", "india", "bengaluru", "bangalore", "brazil", "poland", "australia", "sydney", "paris", "france", "netherlands", "amsterdam", "turkey", "argentina", "budapest"]
ITAR_COMPANIES = ["spacex", "anduril", "lockheed", "northrop", "raytheon", "palantir"]

queued_count = 0
wa_count = 0
us_count = 0

for r_id, p_str in rows:
    j = json.loads(p_str)
    status = j.get("status")
    
    # Don't touch already submitted jobs
    if status == "SUBMITTED":
        continue
        
    title = (j.get("title") or "").lower()
    comp = (j.get("company") or "").lower()
    loc = (j.get("location") or "").lower()
    url = (j.get("applicationUrl") or j.get("applyUrl") or j.get("listingUrl") or "").lower()
    
    # Check if Senior SWE
    is_senior = any(k in title for k in ("senior", "sr.", "sr "))
    is_swe = any(k in title for k in ("software", "engineer", "developer", "backend", "fullstack", "infrastructure", "platform", "systems", "data"))
    
    # Check international
    is_intl = any(term in loc for term in INTERNATIONAL_TERMS) or "eu.greenhouse.io" in url
    
    # Check ITAR
    is_itar = any(it in comp for it in ITAR_COMPANIES)
    
    if not (is_senior and is_swe) or is_intl or is_itar or not url:
        if status in ("QUEUED", "NEEDS_REVIEW"):
            j["status"] = "SKIPPED"
            j["skipReason"] = "Non-Senior-SWE, ITAR, or international"
            cur.execute("UPDATE entities SET payload = ? WHERE id = ?", (json.dumps(j), r_id))
        continue
    
    # Check if WA (Seattle / Bellevue / Redmond / WA)
    is_wa = any(w in loc for w in ("wa", "washington", "seattle", "bellevue", "redmond", "kirkland"))
    
    # Eligible Senior SWE US job!
    j["status"] = "QUEUED"
    j["matchScore"] = max(float(j.get("matchScore") or 0), 88.0)
    j["manualMatchOverride"] = True
    j["lastError"] = None
    j["reviewReason"] = None
    j["lockedBy"] = None
    j["lockedAt"] = None
    j["lockExpiresAt"] = None
    j["tailoringMode"] = "honest"
    
    if is_wa:
        j["priority"] = 100
        wa_count += 1
    else:
        j["priority"] = 50
        us_count += 1
        
    cur.execute("UPDATE entities SET payload = ? WHERE id = ?", (json.dumps(j), r_id))
    queued_count += 1

conn.commit()
print(f"Prepared queue: {queued_count} total Senior SWE US jobs ({wa_count} Tier-1 WA, {us_count} Tier-2 US)")

# List top 15 queued jobs
cur.execute("""
    SELECT id, json_extract(payload, '$.company'), json_extract(payload, '$.title'), json_extract(payload, '$.location'), json_extract(payload, '$.priority'), json_extract(payload, '$.applicationUrl')
    FROM entities
    WHERE entity_type = 'aa_autopilot_job' AND json_extract(payload, '$.status') = 'QUEUED'
    ORDER BY json_extract(payload, '$.priority') DESC, json_extract(payload, '$.createdAt') ASC
    LIMIT 15
""")
print("\n--- TOP 15 QUEUED JOBS READY TO PROCESS ---")
for r in cur.fetchall():
    print(f"[{r[4]}] {r[1]} | {r[2]} | Loc: {r[3]}")

conn.close()
