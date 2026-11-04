import json
from app.db.store import SessionLocal, EntityStore

db = SessionLocal()
failed_anduril = db.query(EntityStore).filter(
    EntityStore.entity_type == "aa_autopilot_job",
    EntityStore.id.in_(["apjob_6f7ebfee-54d7-42db-b495-20d28f8618b5", "apjob_b997ec8c-f818-4e5e-a258-353e069eb7f2"])
).all()

for item in failed_anduril:
    p = dict(item.payload)
    p["status"] = "QUEUED"
    p["lastError"] = None
    item.payload = p

db.commit()
print(f"Reset {len(failed_anduril)} failed Anduril jobs back to QUEUED for clean rerun.")
