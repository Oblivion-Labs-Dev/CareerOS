# CareerOS — Modular Monolith Refactor Plan

## Goal

Restructure the backend so every business domain is a top-level sibling folder
with its own `models`, `schemas`, `enums`, `config`, `interfaces`, `router`,
`service`, and `repository`. No `modules/` wrapper — each folder IS the service.
The monolith stays one deployable binary; any folder can be lifted out into its
own process later with zero changes to the other folders.

## Non-goals

- Do not touch the Chrome extension (`extension/`)
- Do not touch `frontend/` routing or pages yet — only the API-layer contracts
  (`frontend/*/api.ts` files get updated paths at the end)
- Do not change database schema or SQLite file location
- Do not change any env variables

---

## Target top-level layout

```
CareerOS/
├── resume/             ← Resume Intelligence (parse, profile, store, tailoring)
├── jobs/               ← Job Discovery (scrape, score, index, filter)
├── autopilot/          ← Application Engine (browser, forms, queue, submission)
├── profile/            ← Candidate Profile (flat fields, screening answers)
├── intelligence/       ← AI / LLM Orchestration (answer gen, story corpus)
├── notifications/      ← Communications (Gmail, email tracking, receipts)
├── analytics/          ← Observability (metrics, diagnostics, error tracking)
├── shared/             ← Cross-cutting contracts only — NO business logic
│   ├── db.py           # session factory + Base
│   ├── events.py       # event type definitions
│   └── types.py        # primitive shared types (IDs, timestamps)
├── main.py             ← monolith assembler — imports routers, nothing else
│
├── frontend/           (unchanged structure)
├── extension/          (unchanged)
├── packages/           (unchanged)
├── infra/              (unchanged)
└── apps/               (deleted after migration is verified)
```

Each service folder has this internal structure — no exceptions:

```
<service>/
├── __init__.py
├── models.py           # SQLAlchemy table models owned by this service
├── schemas.py          # Pydantic request/response types
├── enums.py            # Enums used by this service
├── config.py           # Service-specific settings (reads from shared env)
├── interfaces.py       # Public Protocol — the ONLY file other services import
├── router.py           # FastAPI APIRouter
├── service.py          # Business logic — implements the interface
├── repository.py       # DB reads/writes — nothing else accesses this directly
└── docs/               # <service>-overview.md, any ADRs
```

Sub-folders inside a service (only when needed):

```
autopilot/
├── browser/            # runner.py, executor.py, recovery.py, replay.py
├── forms/              # fill_engine.py, mapping_agent.py, adapters/
└── repair/             # self_healer.py, repair_agent.py
```

---

## The cross-service contract rule

**Services never import from another service's `service.py`, `repository.py`,
or internal files. They only import from `<service>/interfaces.py`.**

```python
# CORRECT — autopilot calls resume through its interface
from resume.interfaces import IResumeService

# WRONG — never do this
from resume.service import ResumeService
from resume.repository import get_profile_from_db
```

This means extraction to a microservice = write one `ResumeHttpClient` that
implements `IResumeService` and replace the injection. Nothing else changes.

Inter-service async communication uses `shared/events.py`:

```python
# publisher
from shared.events import emit
await emit("application.submitted", {"job_id": job_id, "application_id": aid})

# subscriber (in jobs/service.py)
from shared.events import on
@on("application.submitted")
async def handle(payload): ...
```

---

## Source → target file mapping

### Step 1 — Create `shared/`

| Create | Content |
|---|---|
| `shared/__init__.py` | empty |
| `shared/db.py` | move `apps/api/app/db/store.py` session factory + Base only |
| `shared/events.py` | new — simple in-process pub/sub (dict of `event → [handlers]`) |
| `shared/types.py` | new — `ServiceId = str`, `IsoTimestamp = str`, etc. |

Keep `apps/api/app/db/store.py` in place and have it re-export from `shared.db`
until all imports are updated. Delete the re-export at the end.

---

### Step 2 — `resume/` service

**What it owns:** everything to do with parsing a resume PDF into structured
data and storing the candidate profile.

| Source | Destination |
|---|---|
| `apps/api/app/services/resume_parser.py` | `resume/parsers/pdf_parser.py` |
| `apps/api/app/services/resume_structure.py` | `resume/parsers/structure_parser.py` |
| `apps/api/app/services/resume_intelligence/resume_profiles.py` | `resume/repository.py` (merge) |
| `apps/api/app/services/resume_intelligence/ats_score.py` | `resume/ats_score.py` |
| `apps/api/app/services/resume_intelligence/resume_studio.py` | `resume/studio.py` |
| `apps/api/app/services/resume_intelligence/persistence.py` | `resume/repository.py` (merge) |
| `apps/api/app/services/resume_intelligence/scanner.py` | `resume/scanner.py` |
| `apps/api/app/services/resume_intelligence/tailoring.py` | `resume/tailoring.py` |
| `apps/api/app/services/resume_intelligence/minimal_tailoring.py` | `resume/tailoring.py` (merge) |
| `apps/api/app/services/resume_intelligence/deterministic_tailor.py` | `resume/tailoring.py` (merge) |
| `apps/api/app/services/resume_intelligence/quality.py` | `resume/quality.py` |
| `apps/api/app/services/resume_intelligence/local_composer.py` | `resume/composer.py` |
| `apps/api/app/services/resume_intelligence/local_document.py` | `resume/composer.py` (merge) |
| `apps/api/app/services/resume_intelligence/baseline_document.py` | `resume/composer.py` (merge) |
| `apps/api/app/services/resume_intelligence/text_utils.py` | `resume/parsers/text_utils.py` |
| `apps/api/app/services/resume_intelligence/semantic.py` | `resume/scoring/semantic.py` |
| `apps/api/app/services/resume_intelligence/bm25.py` | `resume/scoring/bm25.py` |
| `apps/api/app/services/resume_intelligence/match_engine.py` | `resume/scoring/match_engine.py` |
| `apps/api/app/services/resume_intelligence/fusion.py` | `resume/scoring/fusion.py` |
| `apps/api/app/services/resume_intelligence/evidence_match.py` | `resume/scoring/evidence_match.py` |
| `apps/api/app/services/resume_intelligence/graph_builder.py` | `resume/scoring/graph_builder.py` |
| `apps/api/app/services/resume_intelligence/corpus_adapter.py` | `resume/scoring/corpus_adapter.py` |
| `apps/api/app/db/resume_corpus_seed.py` | `resume/seed.py` |

**Routes to move** from `apps/api/app/routers/api.py` into `resume/router.py`:

```
GET  /documents/resume
POST /documents/resume
POST /api/parse-resume
GET  /profile/resume-profiles
POST /profile/resume-profiles
PATCH /profile/resume-profiles/{profile_id}
DELETE /profile/resume-profiles/{profile_id}
POST /profile/resume-profiles/{profile_id}/set-default
GET  /resume/ats-score        (from routers/resume_intelligence.py)
POST /resume/export-pdf
POST /resume/generate
POST /resume/studio
POST /resume/tailor
POST /resume/tailor/approve
```

**`resume/interfaces.py`** must expose:
```python
class IResumeService(Protocol):
    async def get_profile(self) -> dict: ...
    async def update_profile(self, patch: dict) -> dict: ...
    async def parse_resume(self, force: bool) -> dict: ...
    async def get_default_resume(self) -> dict | None: ...
    async def save_default_resume(self, payload: dict) -> dict: ...
    def list_resume_profiles(self, db) -> list: ...
```

---

### Step 3 — `jobs/` service

**What it owns:** discovering, indexing, scoring, and filtering job listings.

| Source | Destination |
|---|---|
| `apps/api/app/services/job_discover/` (entire dir) | `jobs/discovery/` |
| `apps/api/app/services/target_company_jobs.py` | `jobs/target_companies.py` |
| `apps/api/app/services/job_search/job_evaluation.py` | `jobs/evaluation.py` |
| `apps/api/app/services/job_search/posting_legitimacy.py` | `jobs/evaluation.py` (merge) |
| `apps/api/app/services/job_search/outcome_archive.py` | `jobs/outcomes.py` |
| `apps/api/app/services/job_search/html_report.py` | `jobs/report.py` |
| `apps/api/app/services/job_search/methodology.py` | `jobs/docs/methodology.md` (it's docs, not code) |

**Routes to move** from `api.py` and `routers/job_search.py` into `jobs/router.py`:

```
GET  /jobs
POST /jobs/save
POST /jobs/extract
GET  /jobs/companies
POST /jobs/companies
POST /jobs/companies/discover
GET  /jobs/target-companies
POST /jobs/target-companies/refresh
POST /jobs/target-companies/oracle-seed
GET  /jobs/target-companies/whatsapp
GET  /jobs/discover
GET  /jobs/discover/status
GET  /jobs/discover/sources/health
GET  /jobs/discover/sources/report
GET  /jobs/discover/stats
GET  /jobs/discover/filter-options
GET  /jobs/discover/locations
GET  /jobs/discover/lookup
GET  /jobs/discover/{job_id}/recruiter
POST /jobs/discover/scrape
POST /jobs/discover/scrape/cancel
POST /jobs/discover/rescore
POST /jobs/discover/analyze
POST /jobs/discover/gap-analysis
POST /jobs/discover/{job_id}/save
POST /jobs/discover/{job_id}/dismiss
POST /jobs/discover/{job_id}/undismiss
POST /jobs/discover/{job_id}/message
```

**`jobs/interfaces.py`** must expose:
```python
class IJobService(Protocol):
    async def trigger_scrape(self) -> dict: ...
    def get_status(self, db) -> dict: ...
    def list_discovered(self, db, filters: dict) -> dict: ...
    def get_job(self, db, job_id: str) -> dict: ...
```

---

### Step 4 — `profile/` service

**What it owns:** the flat candidate profile fields used by application forms
(address, work auth, salary, screening answers). Does NOT own resume files
(that's `resume/`) or experience arrays used for intelligence (that's
`intelligence/`).

| Source | Destination |
|---|---|
| Profile CRUD logic in `apps/api/app/routers/api.py` (lines around `GET /profile`, `POST /profile`) | `profile/service.py` |
| `apps/api/app/services/profile_normalizer.py` | `profile/normalizer.py` |
| `apps/api/app/services/settings/memory.py` | `profile/memory.py` |
| `apps/api/app/services/settings/portfolio.py` | `profile/portfolio.py` |

**Routes to move** into `profile/router.py`:

```
GET  /profile
POST /profile
GET  /settings/memory
POST /settings/memory
DELETE /settings/memory/{note_id}
GET  /public/portfolio/{slug}
```

**`profile/interfaces.py`** must expose:
```python
class IProfileService(Protocol):
    def get(self, db) -> dict: ...
    def update(self, db, patch: dict) -> dict: ...
```

---

### Step 5 — `autopilot/` service

**What it owns:** browser automation, form filling, the application queue, and
submission tracking. The largest service.

| Source | Destination |
|---|---|
| `apps/api/app/services/application_assistant/browser_runner.py` | `autopilot/browser/runner.py` |
| `apps/api/app/services/application_assistant/playwright_autopilot_executor.py` | `autopilot/browser/executor.py` |
| `apps/api/app/services/application_assistant/adaptive_browser_recovery.py` | `autopilot/browser/recovery.py` |
| `apps/api/app/services/application_assistant/browser_replay.py` | `autopilot/browser/replay.py` |
| `apps/api/app/services/application_assistant/browser_fingerprint.py` | `autopilot/browser/fingerprint.py` |
| `apps/api/app/services/application_assistant/stealth_browser_profile.py` | `autopilot/browser/stealth.py` |
| `apps/api/app/services/application_assistant/browser_verifier.py` | `autopilot/browser/verifier.py` |
| `apps/api/app/services/application_assistant/field_fill_engine.py` | `autopilot/forms/fill_engine.py` |
| `apps/api/app/services/application_assistant/field_mapping_agent.py` | `autopilot/forms/mapping_agent.py` |
| `apps/api/app/services/application_assistant/form_field_persistence.py` | `autopilot/forms/persistence.py` |
| `apps/api/app/services/application_assistant/css_selectors.py` | `autopilot/forms/css_selectors.py` |
| `apps/api/app/services/application_assistant/field_options.py` | `autopilot/forms/field_options.py` |
| `apps/api/app/services/application_assistant/canonical_registry.py` | `autopilot/forms/canonical_registry.py` |
| `apps/api/app/services/application_assistant/semantic_field_resolution.py` | `autopilot/forms/semantic_resolution.py` |
| `apps/api/app/services/application_assistant/mapping_pipeline.py` | `autopilot/forms/mapping_pipeline.py` |
| `apps/api/app/services/application_assistant/mapping_validation.py` | `autopilot/forms/mapping_validation.py` |
| `apps/api/app/services/application_assistant/cross_field_validator.py` | `autopilot/forms/cross_field_validator.py` |
| `apps/api/app/services/application_assistant/greenhouse_schema.py` | `autopilot/forms/adapters/greenhouse.py` |
| `apps/api/app/services/application_assistant/greenhouse_verification_service.py` | `autopilot/forms/adapters/greenhouse.py` (merge) |
| `apps/api/app/services/application_assistant/queue_preprocessor.py` | `autopilot/queue/preprocessor.py` |
| `apps/api/app/services/application_assistant/worker.py` | `autopilot/queue/worker.py` |
| `apps/api/app/services/application_assistant/submission_pacing.py` | `autopilot/queue/pacing.py` |
| `apps/api/app/services/application_assistant/application_list_priority.py` | `autopilot/queue/priority.py` |
| `apps/api/app/services/application_assistant/process_manager.py` | `autopilot/queue/process_manager.py` |
| `apps/api/app/services/application_assistant/submission_guard.py` | `autopilot/submission/guard.py` |
| `apps/api/app/services/application_assistant/submission_outcome.py` | `autopilot/submission/outcome.py` |
| `apps/api/app/services/application_assistant/submission_watcher.py` | `autopilot/submission/watcher.py` |
| `apps/api/app/services/application_assistant/submission_receipt_service.py` | `autopilot/submission/receipt.py` |
| `apps/api/app/services/application_assistant/submission_policy.py` | `autopilot/submission/policy.py` |
| `apps/api/app/services/application_assistant/manual_submission_reconciler.py` | `autopilot/submission/manual_reconciler.py` |
| `apps/api/app/services/application_assistant/repair_agent.py` | `autopilot/repair/agent.py` |
| `apps/api/app/services/application_assistant/autopilot_self_healer.py` | `autopilot/repair/self_healer.py` |
| `apps/api/app/services/application_assistant/healing_response.py` | `autopilot/repair/healing_response.py` |
| `apps/api/app/services/application_assistant/failure_controller.py` | `autopilot/repair/failure_controller.py` |
| `apps/api/app/services/application_assistant/failure_taxonomy.py` | `autopilot/repair/failure_taxonomy.py` |
| `apps/api/app/services/application_assistant/autopilot_runner.py` | `autopilot/service.py` |
| `apps/api/app/services/application_assistant/persistence.py` | `autopilot/repository.py` |
| `apps/api/app/services/application_assistant/domain.py` | `autopilot/enums.py` + `autopilot/models.py` (split) |
| `apps/api/app/services/application_assistant/job_matching.py` | `autopilot/matching/job_matching.py` |
| `apps/api/app/services/application_assistant/job_filter_ranker.py` | `autopilot/matching/ranker.py` |
| `apps/api/app/services/application_assistant/role_shape_match.py` | `autopilot/matching/role_shape.py` |
| `apps/api/app/services/application_assistant/tailored_match.py` | `autopilot/matching/tailored.py` |
| `apps/api/app/services/application_assistant/mistral_resume_match.py` | `autopilot/matching/resume_match.py` |
| `apps/api/app/services/application_assistant/candidate_match_context.py` | `autopilot/matching/context.py` |
| All remaining `application_assistant/` files | `autopilot/` (flat, re-evaluate each) |
| `apps/api/app/services/repair/` (entire dir) | `autopilot/repair/` (merge with above) |

**Routes to move** (from `api.py` + application_assistant router) into `autopilot/router.py`:

```
GET  /applications
POST /applications
POST /applications/import
GET  /autofill/mappings
POST /autofill/map-field
POST /questions/answer
GET  /benchmarks
POST /benchmarks/run
POST /benchmarks/test-resolve
+ everything currently in routers/application_assistant/__init__.py
```

---

### Step 6 — `intelligence/` service

**What it owns:** LLM orchestration, the story/experience corpus, gap analysis,
and AI-powered signals. Does NOT own form-filling LLM calls (that stays in
`autopilot/`) — only cross-job career intelligence.

| Source | Destination |
|---|---|
| `apps/api/app/services/llm.py` | `intelligence/llm/client.py` |
| `apps/api/app/services/answer_engine.py` | `intelligence/answer_engine.py` |
| `apps/api/app/services/story_index.py` | `intelligence/corpus/story_index.py` |
| `apps/api/app/db/story_corpus_sync.py` | `intelligence/corpus/sync.py` |
| `apps/api/app/services/intelligence/` (entire dir) | `intelligence/signals/` |
| `apps/api/app/services/gemini/` (entire dir) | `intelligence/providers/gemini/` |
| `apps/api/app/services/career_progress.py` | `intelligence/career_progress.py` |
| `apps/api/app/services/market_trends.py` | `intelligence/market_trends.py` |

**Routes to move** (from `routers/intelligence.py` + `routers/story_map.py`) into `intelligence/router.py`.

---

### Step 7 — `notifications/` service

**What it owns:** all email I/O — Gmail IMAP polling, outbound email, tracking
pixels, and receipt parsing.

| Source | Destination |
|---|---|
| `apps/api/app/services/gmail_imap.py` | `notifications/gmail/imap.py` |
| `apps/api/app/services/gmail_sender.py` | `notifications/gmail/sender.py` |
| `apps/api/app/services/tracking_email.py` | `notifications/tracking.py` |
| `apps/api/app/services/outreach_campaign_store.py` | `notifications/outreach.py` |
| `apps/api/app/services/bounce_classifier.py` | `notifications/bounce.py` |
| `apps/api/app/services/tracker/` (entire dir) | `notifications/tracker/` |
| `apps/api/app/services/application_assistant/inbound_email_tracker.py` | `notifications/tracker/inbound.py` |

**Routes to move** (from `routers/gmail_archive.py` and `api.py`):

```
GET  /email/outreach-campaigns
GET  /email/recruiter-conversations
GET  /email/recruiter-threads
GET  /email/recruiter-threads/classified
GET  /email/verify
POST /email/send
POST /tracker/sync-gmail
```

---

### Step 8 — `analytics/` service

**What it owns:** metrics, diagnostics, error investigation, outcome analysis,
and observability. Read-heavy, no writes to other services' tables.

| Source | Destination |
|---|---|
| `apps/api/app/routers/diagnostic.py` | `analytics/router.py` |
| `apps/api/app/services/diagnostic_outcomes.py` | `analytics/outcomes.py` |
| `apps/api/app/services/diagnostic_series.py` | `analytics/series.py` |
| `apps/api/app/services/observability.py` | `analytics/observability.py` |
| `apps/api/app/services/runtime_metrics.py` | `analytics/metrics.py` |
| `apps/api/app/services/model_usage_tracker.py` | `analytics/model_usage.py` |
| `apps/api/app/services/api_dashboard.py` | `analytics/dashboard.py` |
| `apps/api/app/services/log_store.py` | `analytics/log_store.py` |
| `apps/api/app/services/error_fix_tracker.py` | `analytics/error_tracker.py` |
| `apps/api/app/services/error_investigation.py` | `analytics/error_investigation.py` |
| `apps/api/app/services/noise_routes.py` | `analytics/signal_noise.py` |
| `apps/api/app/services/retention.py` | `analytics/retention.py` |

**Routes to move** into `analytics/router.py`:

```
GET  /metrics
GET  /errors/{error_id}/investigate
POST /errors/{error_id}/investigate
POST /errors/investigate-open
GET  /api/logs
POST /api/logs
DELETE /api/logs
GET  /api/db
+ all of routers/diagnostic.py
```

---

### Step 9 — Remaining files (decide per file)

| File | Decision |
|---|---|
| `apps/api/app/services/auth.py` | → `shared/auth.py` (it's middleware-level) |
| `apps/api/app/services/safe_write.py` | → `shared/safe_write.py` |
| `apps/api/app/services/read_cache.py` | → `shared/cache.py` |
| `apps/api/app/services/structured_errors.py` | → `shared/errors.py` |
| `apps/api/app/services/extension_packager.py` | → `analytics/extension_packager.py` or delete |
| `apps/api/app/services/uat/` | → `shared/uat/` (test fixtures, used across services) |
| `apps/api/app/services/settings/` | settings now live in each service's `config.py` |
| `apps/api/app/middleware/` | → `shared/middleware/` |

---

### Step 10 — `main.py` (monolith assembler)

After all services are migrated, `main.py` at the repo root should look like:

```python
from fastapi import FastAPI
from shared.db import engine, Base
from shared.middleware import auth, metrics, structured_errors

from resume.router      import router as resume_router
from jobs.router        import router as jobs_router
from autopilot.router   import router as autopilot_router
from profile.router     import router as profile_router
from intelligence.router import router as intelligence_router
from notifications.router import router as notifications_router
from analytics.router   import router as analytics_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="CareerOS")
app.add_middleware(auth.AuthMiddleware)
app.add_middleware(metrics.MetricsMiddleware)

app.include_router(resume_router,       prefix="/resume")
app.include_router(jobs_router,         prefix="/jobs")
app.include_router(autopilot_router,    prefix="/autopilot")
app.include_router(profile_router,      prefix="/profile")
app.include_router(intelligence_router, prefix="/intelligence")
app.include_router(notifications_router, prefix="/notifications")
app.include_router(analytics_router,    prefix="/analytics")
```

---

### Step 11 — Update frontend API clients

Every `frontend/*/api.ts` file that calls an old path needs updating.
Key path changes:

| Old path | New path |
|---|---|
| `/documents/resume` | `/resume/documents` |
| `/api/parse-resume` | `/resume/parse` |
| `/profile/resume-profiles` | `/resume/profiles` |
| `/autofill/mappings` | `/autopilot/autofill/mappings` |
| `/autofill/map-field` | `/autopilot/autofill/map-field` |
| `/questions/answer` | `/autopilot/questions/answer` |
| `/email/...` | `/notifications/email/...` |
| `/tracker/sync-gmail` | `/notifications/tracker/sync` |
| `/metrics` | `/analytics/metrics` |
| `/errors/...` | `/analytics/errors/...` |
| `/api/logs` | `/analytics/logs` |

All other paths (`/jobs/*`, `/profile`, `/resume/*`, `/applications`) keep the
same suffix — just gain the service prefix where missing.

---

### Step 12 — Delete `apps/`

Once all routes are verified working under the new layout:

```bash
rm -rf apps/
```

Update `docker-compose.yml` references from `apps/api/Dockerfile` →
`Dockerfile` at repo root (or each service has its own).

---

## Implementation order

Do one service at a time. Validate before moving to the next.

1. `shared/` — foundation, no routes (1–2 hours)
2. `profile/` — smallest surface, 2 routes, no sub-folders (2–3 hours)
3. `analytics/` — read-only, safe to break in isolation (2–3 hours)
4. `notifications/` — no dependencies on other services (3–4 hours)
5. `resume/` — medium complexity, 14 routes (4–6 hours)
6. `jobs/` — 28 routes, complex scraper logic (4–6 hours)
7. `intelligence/` — LLM + corpus, dependencies on resume interface (4–6 hours)
8. `autopilot/` — largest, 90+ files, do last (1–2 days)
9. Update frontend API clients (2–3 hours)
10. Delete `apps/`, update Docker (1 hour)

## Validation after each step

After migrating each service:

```bash
# API starts
curl http://localhost:4000/health

# All routes respond (not 404)
python -m pytest apps/api/tests/ -q

# Typecheck frontend
pnpm -r run typecheck

# Pre-commit hook passes
git commit --dry-run
```

## Key rules for the Claude session executing this

1. **Move files with `git mv`** — preserves history.
2. **Update imports immediately** after each move — do not leave broken imports.
3. **One service per commit** — if something breaks, it's easy to revert.
4. **Never import across services except through `interfaces.py`** — if you
   find a cross-service import that isn't going through an interface, define
   the interface first.
5. **Do not change any function signatures** during the move — this is a
   structural refactor, not a logic refactor.
6. **Keep `apps/api/` intact until Step 12** — run both old and new paths in
   parallel by having `main.py` import from both during transition.
