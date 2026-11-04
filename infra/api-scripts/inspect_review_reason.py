import sqlite3
import json

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()

cur.execute("""
    SELECT id, payload FROM entities WHERE id IN ('apjob_62b67f09', 'apjob_560ea07e')
""")
for r_id, p_str in cur.fetchall():
    j = json.loads(p_str)
    print(f"=== Job {r_id}: {j.get('company')} - {j.get('title')} ===")
    print("Keys:", list(j.keys()))
    print("URLs:", {k: v for k, v in j.items() if "url" in k.lower() or "link" in k.lower()})
    print("Status:", j.get("status"))
    print("LastError:", j.get("lastError"))
    print("ReviewReason:", j.get("reviewReason"))
    print("AIExplanation:", j.get("aiExplanation"))
    sub_ev = j.get("submissionEvidence") or {}
    dom_v = sub_ev.get("domVerification") or {}
    if dom_v.get("issues"):
        print("DOM Verification Issues:")
        for iss in dom_v["issues"]:
            print("  -", iss.get("issueType"), "|", iss.get("label"), "| intended:", iss.get("intendedValue"), "| actual:", iss.get("actualDomValue"), "| details:", iss.get("details"))
    print()
