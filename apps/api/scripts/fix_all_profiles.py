import json
import sqlite3
from pathlib import Path

# Canonical profile data
PROFILE_DATA = {
    "firstName": "Akshay",
    "lastName": "Borse",
    "fullName": "Akshay Borse",
    "preferredName": "Akshay",
    "email": "amsborse@gmail.com",
    "phone": "(425) 336-9852",
    "phoneCountryCode": "+1",
    "city": "Seattle",
    "state": "Washington",
    "location": "Seattle, WA",
    "country": "United States",
    "zip": "98101",
    "currentCompany": "Microsoft",
    "currentTitle": "Senior Software Engineer",
    "targetRole": "Senior Software Engineer",
    "yearsExperience": "9",
    "sponsorship": "No",
    "requiresSponsorship": "No",
    "workAuthorization": "Yes",
    "authorizedToWorkInUS": "Yes",
    "workAuth": {
        "authorizedToWorkInUS": True,
        "requiresSponsorshipNowOrFuture": False,
        "authorizationType": "Authorized",
        "permanentWorkAuthorization": True,
        "usCitizen": False,
        "usNational": False,
        "greenCardHolder": False
    },
    "raceEthnicity": "Asian",
    "race": "Asian",
    "ethnicity": "Asian",
    "gender": "Decline To Self Identify",
    "hispanic": "No",
    "veteran": "I am not a protected veteran",
    "disability": "No, I do not have a disability",
    "linkedin": "https://www.linkedin.com/in/amsborse/",
    "github": "https://github.com/amsborse",
    "portfolio": "",
    "smsConsent": "Yes",
    "accuracyConfirmation": "Yes",
    "screeningAnswers": [
        {
            "id": "legal_age",
            "question": "Are you over 18 years of age?",
            "answer": "Yes",
            "matchPatterns": [r"18\s+years", r"over\s+18", r"at\s+least\s+18", r"legal\s+age"]
        },
        {
            "id": "work_auth_us",
            "question": "Are you legally authorized to work in the United States?",
            "answer": "Yes",
            "matchPatterns": [r"authorized\s+to\s+work", r"eligible\s+to.*work"]
        },
        {
            "id": "sponsorship_us",
            "question": "Will you now or in the future require visa sponsorship?",
            "answer": "No",
            "matchPatterns": [r"require.*sponsor", r"need.*sponsor", r"visa\s+sponsor"]
        },
        {
            "id": "company_history_robinhood",
            "question": "Have you ever worked for Robinhood as an employee, intern or contractor?",
            "answer": "No",
            "matchPatterns": [r"ever\s+worked\s+for"]
        }
    ],
    "customFields": {
        "city": "Seattle",
        "state": "Washington",
        "postalCode": "98101",
        "zip": "98101",
        "country": "United States"
    }
}

# 1. Update SQLite DB (kv_store + entities)
db_path = Path("data/career_os.db")
if db_path.exists():
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Get existing kv_store profile to preserve workExperience and other complex nested structures
    cur.execute("SELECT value FROM kv_store WHERE key = 'profile'")
    row = cur.fetchone()
    if row:
        existing = json.loads(row[0])
    else:
        existing = {}

    merged = {**existing, **PROFILE_DATA}
    # Ensure workExperience is kept
    if "workExperience" in existing:
        merged["workExperience"] = existing["workExperience"]

    cur.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES ('profile', ?)", (json.dumps(merged),))
    print("Updated kv_store profile successfully.")

    # Update resume_profile entity if exists
    cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'resume_profile'")
    for r_id, payload_str in cur.fetchall():
        ent = json.loads(payload_str)
        ent.update({
            "city": "Seattle",
            "state": "Washington",
            "location": "Seattle, WA",
            "sponsorship": "No",
            "workAuthorization": "Yes",
            "workAuth": PROFILE_DATA["workAuth"],
            "raceEthnicity": "Asian",
            "hispanic": "No"
        })
        cur.execute("UPDATE entities SET payload = ? WHERE id = ?", (json.dumps(ent), r_id))
        print(f"Updated resume_profile {r_id} successfully.")

    conn.commit()
    conn.close()

# 2. Update applypilot-profile.json
ap_path = Path("data/applypilot-profile.json")
if ap_path.exists():
    try:
        ap_data = json.loads(ap_path.read_text(encoding="utf-8"))
    except Exception:
        ap_data = {}
    ap_data.update(PROFILE_DATA)
    ap_path.write_text(json.dumps(ap_data, indent=2), encoding="utf-8")
    print("Updated applypilot-profile.json successfully.")

# 3. Update apps/extension/db.json
ext_path = Path("../extension/db.json")
if ext_path.exists():
    try:
        ext_data = json.loads(ext_path.read_text(encoding="utf-8"))
    except Exception:
        ext_data = {}
    ext_prof = ext_data.get("profile", {})
    ext_prof.update(PROFILE_DATA)
    ext_data["profile"] = ext_prof
    ext_path.write_text(json.dumps(ext_data, indent=2), encoding="utf-8")
    print("Updated extension/db.json successfully.")

print("All profiles cleanly updated and aligned.")
