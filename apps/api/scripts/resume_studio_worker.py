"""Read-only studio worker for a web dev server whose API predates the new route.

Input is a JSON snapshot on stdin; output is JSON on stdout. Never starts the
main API or application runner, writes the profile, or invokes a paid provider.
"""
import contextlib
import json
from pathlib import Path
import sys

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

if __name__ == "__main__":
    # Reuse the shared composer's embedding cache for consecutive previews.
    # The parent closes this worker after a short idle period to release memory.
    for line in sys.stdin:
        try:
            payload = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                from app.services.resume_intelligence.resume_studio import generate_studio
                result = generate_studio(payload["records"], payload["profile"], payload["jobDescription"],
                                         payload.get("targetRole", ""), payload.get("targetCompany", ""))
            print(json.dumps({"success": True, **result}), flush=True)
        except ValueError as exc:
            print(json.dumps({"success": False, "detail": str(exc)}), flush=True)
        except Exception:
            print(json.dumps({"success": False, "detail": "Resume rendering failed. Check the local API dependencies and try again."}), flush=True)
