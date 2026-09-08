import os

log_path = os.path.join(os.path.dirname(__file__), "..", "data", "logs", "api.log")
with open(log_path, "rb") as f:
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(max(0, size - 10000), os.SEEK_SET)
    lines = f.read().decode("utf-8", errors="ignore").splitlines()

print(f"Total lines in last 10KB: {len(lines)}")
for l in lines[-25:]:
    print(l.encode("ascii", errors="replace").decode("ascii"))
