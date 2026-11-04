import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx

try:
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=15) as client:
        client.post("/auth/login", json={"username": "amsborse@gmail.com", "password": "CareerOS12$"})
        res = client.get("/application-assistant/autopilot/status")
        data = res.json()
        print("Status Code:", res.status_code)
        print("Running:", data.get("running"))
        ar = data.get("activeRun") or {}
        print(f"Active Run: {ar.get('id')} | Status: {ar.get('status')}")
        print(f"Processed: {ar.get('processedCount', 0)} / {ar.get('targetProcessCount', 0)}")
        print(f"Submitted: {ar.get('submittedCount', 0)} | Skipped: {ar.get('skippedCount', 0)} | Failed: {ar.get('failedCount', 0)}")
        
        workers = data.get("workers") or []
        print(f"\nActive Workers ({len(workers)}):")
        if isinstance(workers, dict):
            worker_list = sorted(workers.values(), key=lambda x: x.get("slot", 0))
        else:
            worker_list = workers
        for w in worker_list:
            slot = w.get("slot")
            comp = w.get("current_company") or "Idle"
            tit = w.get("current_title") or ""
            step = w.get("current_step") or w.get("status") or "idle"
            print(f"  Slot {slot}: [{w.get('status')}] {comp} - {tit} | Step: {step}")
            
        print("\nRecent Logs (last 12):")
        for l in data.get("recentLogs", [])[-12:]:
            print(f"  [{l.get('level', 'info').upper()}] {l.get('message')}")
except Exception as e:
    print("Error querying status:", e)
