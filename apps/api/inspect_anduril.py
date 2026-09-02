import json
from app.db.store import SessionLocal, EntityStore

db = SessionLocal()
entities = db.query(EntityStore).filter(EntityStore.entity_type.in_(["aa_autopilot_job", "aa_job_lead", "application"])).all()

anduril_jobs = []
for e in entities:
    raw = json.dumps(e.payload).lower()
    if "anduril" in raw:
        anduril_jobs.append((e.entity_type, e.id, e.payload))

print(f"Total Anduril records found: {len(anduril_jobs)}")

for entity_type, eid, p in anduril_jobs:
    status = p.get("status")
    title = p.get("title") or p.get("role") or p.get("job_title")
    company = p.get("company") or p.get("company_name")
    last_error = p.get("lastError") or p.get("error") or p.get("failureReason") or p.get("reason")
    url = p.get("applicationUrl") or p.get("listingUrl") or p.get("url")
    
    print("\n" + "="*50)
    print(f"Type: {entity_type} | ID: {eid}")
    print(f"Role: {title} @ {company}")
    print(f"Status: {status}")
    print(f"Error / Failure Reason: {last_error}")
    print(f"URL: {url}")
    if "steps" in p:
        print("Steps:", json.dumps(p["steps"], indent=2)[:500])
    if "formFields" in p:
        print("Form Fields:", json.dumps(p["formFields"], indent=2)[:500])
    if "resolution_log" in p:
        print("Resolution Log:", json.dumps(p["resolution_log"], indent=2)[:500])
