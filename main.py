"""CareerOS monolith entry point.

Run with:  uvicorn main:app  (from the repository root)

The business-domain packages live at the repo root alongside this file:
  shared/, profile/, analytics/, notifications/, resume/, jobs/,
  intelligence/, autopilot/

The FastAPI application and its lifecycle are assembled in app/main.py.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.main import app  # noqa: E402

__all__ = ["app"]
