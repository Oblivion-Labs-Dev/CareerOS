import os

log_path = os.path.join(os.path.dirname(__file__), "..", "data", "logs", "api.log")
with open(log_path, "rb") as f:
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(max(0, size - 150000), os.SEEK_SET)
    lines = f.read().decode("utf-8", errors="ignore").splitlines()

# Filter out uvicorn access logs and health checks
filtered = [l for l in lines if "[uvicorn.access]" not in l and "GET /health" not in l and "GET /applications" not in l and "GET /api/autopilot" not in l]
print(f"Total lines in window: {len(filtered)}")
for l in filtered[-50:]:
    print(l)
