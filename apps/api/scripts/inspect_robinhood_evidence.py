import sqlite3
import json

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()

cur.execute("SELECT payload FROM entities WHERE id = 'apjob_8a7b043e-4601-4253-9721-ce7e32ab5913'")
p = json.loads(cur.fetchone()[0])

sub = p.get("submissionEvidence") or {}
print("Status:", p.get("status"))
print("Last Error:", p.get("lastError"))

print("\n--- FILLED FIELDS ---")
for k, v in (sub.get("fieldValues") or {}).items():
    print(f"  {k}: {v}")

print("\n--- DOM VALUES ---")
for k, v in (sub.get("domVerification", {}).get("domValues") or {}).items():
    print(f"  {k}: {v}")

print("\n--- DOM ISSUES ---")
for iss in sub.get("domVerification", {}).get("issues") or []:
    print("  *", iss)

conn.close()
