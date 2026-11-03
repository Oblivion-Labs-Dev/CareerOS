"""CareerOS API package.

During the modular-monolith refactor the new top-level service folders
(``shared/``, ``resume/``, ``jobs/`` …) live at the repository root, alongside
``apps/api/app/``. The API is still started as ``app.main:app`` from
``apps/api/`` during the transition, which only puts ``apps/api/`` on
``sys.path``. Insert the repo root here so ``import shared.*`` (and the other
service packages) resolve while both layouts coexist. This bridge is removed
once the app is started as ``main:app`` from the repo root (Step 10) and
``apps/`` is deleted (Step 12).
"""

import sys as _sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))
