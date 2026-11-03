# Refactor notes — modular-monolith restructure

Running log of decisions, deviations from `plan.md`, and anything a reviewer
should know. The refactor runs in this worktree; the live dev server runs from
the main checkout's `apps/api/`, so validation here is import-level plus the
full pytest suite (1300+ tests) rather than hitting the worktree's own server.

## Validation harness

- App import: `apps/api/.venv/bin/python3 -c "import app.main"` run from
  `apps/api` (the main checkout's venv against the worktree's code).
- Route table: `app.openapi()["paths"]` checked for presence and no duplicates.
- Tests: `python -m pytest -m "not network"` from `apps/api`.
- `curl http://localhost:4000/health` returns `{"status":"ok","service":...}`
  (the running server is a separate process; the real signal is the import +
  test checks above).

## Transition bridges (removed at Step 10/12)

- `apps/api/app/__init__.py` inserts the repo root on `sys.path` so
  `import shared.*` / `profile.*` / `analytics.*` resolve while the app still
  starts as `app.main:app` from `apps/api/`.
- `apps/api/tests/conftest.py` does the same for the test session.
- `apps/api/app/db/store.py` re-exports the db primitives from `shared.db`.
- `main.py`'s new service routers are imported and included alongside the
  legacy routers; routes keep their original paths (no service prefix yet) so
  the frontend/extension are unaffected until Step 11.

## Deviations from plan.md

- **`GET/POST /api/db` left in `routers/api.py`** (plan Step 8 lists it under
  analytics). It is the Chrome-extension legacy full-DB sync
  (`legacy_db_snapshot` / `import_legacy_db` + `require_legacy_sync_auth`), i.e.
  core data sync, not observability. Moving it would couple analytics to the
  entity store and the legacy-sync auth guard for no benefit. Kept in place.
- **`/` root dashboard and `/health` left in `routers/api.py`.** `/` renders the
  API dashboard (uses `analytics.dashboard`) but is not in any service's route
  list; `/health` must stay trivially available. Both unchanged.
- **`/settings/job-boards` left in `routers/api.py`** (Step 2). It is a static
  stub unrelated to the profile service.

## Path fixes after moves (data/static locations unchanged)

Files that resolved data/template paths relative to `__file__` were updated so
the resolved absolute path is identical to before the move (data stays under
`apps/api/data`, static under `apps/api/app/static`):

- `analytics/dashboard.py` → `apps/api/app/static/api-dashboard/index.html`
- `analytics/log_store.py`, `analytics/observability.py`,
  `analytics/error_tracker.py` → `apps/api/data/...`
- `analytics/error_investigation.py` `REPO_ROOT` → `<repo>/apps` (its original
  value), preserved verbatim since it is embedded in investigation prompts.
