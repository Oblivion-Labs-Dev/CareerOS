"""CareerOS monolith entry point at the repo root.

Run with ``uvicorn main:app`` from the repository root.

During the modular-monolith refactor the business domains were lifted into
top-level packages (``shared/``, ``profile/``, ``analytics/``, ``notifications/``,
``resume/``, ``jobs/``, ``intelligence/``, ``autopilot/``). The FastAPI
application is still assembled in ``apps/api/app/main.py`` — which wires every
router and all startup/shutdown lifecycle — so this root module simply puts both
the repo root and ``apps/api`` on ``sys.path`` and re-exports that assembled
``app``. Keeping a single assembly point avoids duplicating ~400 lines of
lifecycle wiring and guarantees the root entry point and the legacy
``app.main:app`` entry point stay byte-for-byte identical in behaviour.

Once ``apps/`` is removed (Step 12) the assembly moves here and the two
``sys.path`` inserts below go away.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
_APPS_API = _REPO_ROOT / "apps" / "api"

for _p in (str(_REPO_ROOT), str(_APPS_API)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.main import app  # noqa: E402  (import after sys.path is set up)

__all__ = ["app"]
