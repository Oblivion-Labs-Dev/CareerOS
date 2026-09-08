import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import urllib.request
import urllib.error
import json
from app.services.auth import create_session_token, SESSION_COOKIE_NAME

token = create_session_token("admin")

for limit in [500, 200]:
    url = f"http://localhost:4000/application-assistant/autopilot/jobs?status=SUBMITTED&limit={limit}"
    try:
        req = urllib.request.Request(url, headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            print(f"limit={limit} -> SUCCESS, count={len(data.get('jobs', []))}")
    except urllib.error.HTTPError as e:
        print(f"limit={limit} -> FAILED with HTTP {e.code}: {e.read().decode()[:150]}")
