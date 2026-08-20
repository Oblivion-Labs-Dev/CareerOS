import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx

try:
    with httpx.Client(timeout=10) as client:
        res = client.get("http://127.0.0.1:8000/application-assistant/autopilot/status")
        data = res.json()
        print("Status:", data.get("status"))
        print("Running:", data.get("running"))
        print("Cumulative:", data.get("cumulative"))
        active = data.get("activeJob")
        if active:
            print(f"Active Job: {active.get('company')} — {active.get('title')} [{active.get('status')}] (Step: {active.get('currentStep')})")
        print("\nRecent Logs:")
        for l in data.get("recentLogs", [])[-10:]:
            print(f"  [{l.get('level')}] {l.get('message')}")
except Exception as e:
    print("Error querying status:", e)
