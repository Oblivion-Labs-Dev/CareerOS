import sqlite3
import json

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()

cur.execute("SELECT payload FROM entities WHERE id = 'apjob_62b67f09'")
p = json.loads(cur.fetchone()[0])

print("Status:", p.get("status"))
print("Updated:", p.get("updatedAt"))
sub = p.get("submissionEvidence") or {}
print("Filled fields in submissionEvidence:")
for k, v in (sub.get("fieldValues") or {}).items():
    print(f"  {k}: {v}")

print("\nDOM verification values:")
for k, v in (sub.get("domVerification", {}).get("domValues") or {}).items():
    print(f"  {k}: {v}")

print("\nDOM verification issues:")
for iss in sub.get("domVerification", {}).get("issues") or []:
    print("  *", iss)

conn.close()
