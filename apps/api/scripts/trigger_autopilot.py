import sys
import json
import urllib.request
from pathlib import Path

# Add apps/api to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings
from app.services.auth import create_session_token, SESSION_COOKIE_NAME

token = create_session_token(settings.career_os_admin_username)

url = "http://127.0.0.1:8000/application-assistant/autopilot/start"
payload = json.dumps({
    "targetProcessCount": 15,
    "batchSize": 15,
    "concurrency": 2
}).encode("utf-8")

req = urllib.request.Request(
    url,
    data=payload,
    headers={
        "Content-Type": "application/json",
        "Cookie": f"{SESSION_COOKIE_NAME}={token}"
    }
)

try:
    with urllib.request.urlopen(req) as resp:
        print("Status:", resp.status)
        data = json.loads(resp.read().decode())
        print("Response:", json.dumps(data, indent=2))
except urllib.error.HTTPError as e:
    print("HTTPError:", e.code, e.read().decode())
except Exception as e:
    print("Error:", e)
