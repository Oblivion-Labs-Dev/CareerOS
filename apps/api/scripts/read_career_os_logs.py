import os

log_path = os.path.join(os.path.dirname(__file__), "..", "data", "logs", "api.log")
with open(log_path, "rb") as f:
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(max(0, size - 300000), os.SEEK_SET)
    lines = f.read().decode("utf-8", errors="ignore").splitlines()

# Keep career_os logs
cos_lines = [l for l in lines if "[career_os" in l]
print(f"Total career_os lines: {len(cos_lines)}")
for l in cos_lines[-35:]:
    print(l.encode("ascii", errors="replace").decode("ascii"))
