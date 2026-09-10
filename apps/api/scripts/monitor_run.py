import sys
import json
import urllib.request
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings
from app.services.auth import create_session_token, SESSION_COOKIE_NAME

token = create_session_token(settings.career_os_admin_username)

# 1. Check API status
status_url = "http://127.0.0.1:8000/application-assistant/autopilot/status"
req = urllib.request.Request(status_url, headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"})
try:
    with urllib.request.urlopen(req) as resp:
        status_data = json.loads(resp.read().decode())
        print("=== RUN STATUS ===")
        print("Active:", status_data.get("active"))
        print("Run ID:", status_data.get("runId"))
        print("Processed:", status_data.get("processedCount"), "/", status_data.get("targetCount"))
        print("Submitted:", status_data.get("submittedCount"))
        print("Staged/Needs Review:", status_data.get("stagedCount"))
        print("Workers:", status_data.get("workers"))
except Exception as e:
    print("Error fetching status:", e)

db_path = Path(__file__).resolve().parents[1] / "data" / "career_os.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("""
    SELECT id, json_extract(payload, '$.company'), json_extract(payload, '$.title'), json_extract(payload, '$.location'), json_extract(payload, '$.status'), json_extract(payload, '$.updatedAt'), json_extract(payload, '$.tailoringFailed'), json_extract(payload, '$.resumeFilename')
    FROM entities
    WHERE entity_type = 'aa_autopilot_job'
    ORDER BY json_extract(payload, '$.updatedAt') DESC
    LIMIT 10
""")
print("\n=== LATEST 10 JOBS IN DB ===")
for r in cur.fetchall():
    print(f"ID: {r[0]} | Co: {r[1]} | Title: {r[2]} | Loc: {r[3]} | Status: {r[4]} | Updated: {r[5]} | TailoringFailed: {r[6]} | Resume: {r[7]}")

conn.close()
