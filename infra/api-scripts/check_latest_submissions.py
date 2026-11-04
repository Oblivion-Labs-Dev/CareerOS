import sqlite3, json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

db_path = Path(__file__).resolve().parents[1] / "data" / "career_os.db"
conn = sqlite3.connect(str(db_path))
cur = conn.cursor()

cur.execute("PRAGMA table_info(entities)")
cols = [c[1] for c in cur.fetchall()]
print("Columns in entities:", cols)

cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job' ORDER BY rowid DESC LIMIT 20")
rows = cur.fetchall()

print("\n=== LATEST 20 AUTOPILOT JOBS ===")
submitted = 0
for j_id, payload_json in rows:
    payload = json.loads(payload_json) if payload_json else {}
    stat = payload.get("status")
    comp = payload.get("company")
    tit = payload.get("title")
    rf = payload.get("resumeFileUsed")
    tail_fail = payload.get("resumeTailoringFailed")
    rcpt = payload.get("confirmationReceipt")
    loc = payload.get("location") or payload.get("metadata", {}).get("location")
    if stat == "SUBMITTED":
        submitted += 1
    print(f"[{stat}] [{comp}] {tit} ({loc})")
    print(f"   Resume: {rf} | TailoringFailed: {tail_fail} | Receipt: {rcpt}")

print(f"\nTotal shown: {len(rows)} | Total submitted in this slice: {submitted}")

cur.execute("SELECT json_extract(payload, '$.status'), count(*) FROM entities WHERE entity_type = 'aa_autopilot_job' GROUP BY json_extract(payload, '$.status')")
counts = cur.fetchall()
print("\nGlobal Counts in aa_autopilot_job:")
for stat, cnt in counts:
    print(f"  {stat}: {cnt}")
