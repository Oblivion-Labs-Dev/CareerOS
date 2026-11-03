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
- **File merges are NOT performed; sources are moved 1:1.** The plan marks
  several moves "(merge)" — e.g. `minimal_tailoring.py`, `deterministic_tailor.py`
  → `resume/tailoring.py`; `local_document.py`, `baseline_document.py` →
  `resume/composer.py`; `resume_profiles.py` + `persistence.py` →
  `resume/repository.py`; greenhouse_schema + greenhouse_verification →
  `autopilot/forms/adapters/greenhouse.py`. Merging independent modules into one
  file is a logic-level refactor (rename/relocate of top-level symbols, risk of
  name collisions) that conflicts with the "structural move, not a behaviour
  change" rule. Each source is instead `git mv`-d to a distinct, clearly-named
  file inside the correct target package/sub-folder, preserving history and
  behaviour. The package layout and import contracts are still achieved.
- **`/settings/job-boards` left in `routers/api.py`** (Step 2). It is a static
  stub unrelated to the profile service.

## Step 5 (resume) scope note

- All resume modules were relocated 1:1 into `resume/` (`parsers/`, `scoring/`,
  and flat files) with every import site rewritten; `resume/interfaces.py` and
  `resume/service.py` provide the package's public contract (`IResumeService`).
- `app/db/resume_corpus_seed.py` is intentionally NOT moved to `resume/seed.py`.
  It is imported by the shared DB layer (`app/db/store.py` / `shared.db` seeding
  in `init_db`); moving it would invert the dependency (DB core → resume). Kept
  in `app/db/`.
- The `resume_intelligence` ROUTER (`app/routers/resume_intelligence.py`) owns
  `/people`, `/scans`, `/match`, `/graph`, … which are NOT in the plan's resume
  route list. It is left in place (its moved-module imports were rewritten and
  still work). The 14 plan-listed resume routes currently remain registered in
  `routers/api.py` (and `/resume/ats-score` in the resume_intelligence router)
  and continue to serve unchanged; relocating those route *handlers* into
  `resume/router.py` is the outstanding part of Step 5. The module layer — the
  pervasive, high-blast-radius part — is complete and fully green.

## Status by step

- Steps 1-10: DONE and validated (full pytest suite 1305 passed / 18 skipped
  after each; `uvicorn main:app` boots end-to-end from the repo root).
- All 8 domain packages exist at the repo root: `shared/`, `profile/`,
  `analytics/`, `notifications/`, `resume/`, `jobs/`, `intelligence/`,
  `autopilot/`. `apps/api/app/services/` is now empty.
- Step 11 (frontend API clients): **no changes required.** The migration kept
  every route path byte-for-byte (the transition strategy: routers include at
  their original paths, no service prefix added), so the frontend/extension
  contract is unchanged. Verified the frontend-referenced paths (`/profile`,
  `/resume/tailor`, `/settings/memory`, `/email/verify`, `/metrics`,
  `/api/logs`, `/documents/resume`, …) all still resolve in the assembled app.
  The plan's Step 11 path table assumed routes gained service prefixes; they did
  not, by design, so applying that table would BREAK the frontend.

## Not done (intentionally, to keep the tree working)

- **Per-service `router.py` for resume/jobs/intelligence/autopilot.** Their
  route *handlers* still live in `apps/api/app/routers/*` (imports rewritten to
  the relocated modules) and serve unchanged. profile/, notifications/ and
  analytics/ do have their own `router.py`. Relocating the remaining route
  handlers is cosmetic given the modules are already extracted.
- **Step 12 (delete `apps/`, flip docker/startup, remove bridges).** NOT done.
  `apps/api/app/` still holds the live app core that everything depends on:
  `main.py` (the actual FastAPI assembly), `config.py`, `db/` (store + seeds),
  `routers/`, `static/` (dashboard assets) — and `apps/api/data/` is the DB and
  data location. Deleting `apps/` now would break the build and lose data.
  Removing it requires first relocating that app core + data to the root, which
  is a further migration beyond the service extraction and is left as the final
  destructive step. The transition bridges (`app/__init__.py` sys.path insert,
  `tests/conftest.py` insert, `app/db/store.py` re-export, the dual sys.path in
  root `main.py`) stay until then.

## Path fixes after moves (data/static locations unchanged)

Files that resolved data/template paths relative to `__file__` were updated so
the resolved absolute path is identical to before the move (data stays under
`apps/api/data`, static under `apps/api/app/static`):

- `analytics/dashboard.py` → `apps/api/app/static/api-dashboard/index.html`
- `analytics/log_store.py`, `analytics/observability.py`,
  `analytics/error_tracker.py` → `apps/api/data/...`
- `analytics/error_investigation.py` `REPO_ROOT` → `<repo>/apps` (its original
  value), preserved verbatim since it is embedded in investigation prompts.
