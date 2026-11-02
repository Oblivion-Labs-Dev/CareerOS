import sqlite3
import json

conn = sqlite3.connect("apps/api/data/career_os.db")
cursor = conn.cursor()
rows = cursor.execute("SELECT payload FROM entities WHERE entity_type='resume_profile' LIMIT 1").fetchall()
if rows:
    profile = json.loads(rows[0][0])
    print("Found profile keys:", list(profile.keys()))
    # print non-secret fields
    for k in ["fullName", "firstName", "lastName", "email", "phone", "location", "linkedin", "github", "currentTitle", "currentCompany", "yearsOfExperience"]:
        print(f"  {k}: {profile.get(k)}")
else:
    print("No resume_profile found in DB!")
