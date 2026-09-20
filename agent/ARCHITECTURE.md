# CareerOS — Architecture Context for Coding Agents

Persistent orientation document. Read this first, then open only the modules your task
touches. Everything here was derived from the code in this repository.

> `docs/architecture.md` is **stale** (it claims port 8000 and per-entity SQL tables).
> Prefer this file. `AGENTS.md` at the repo root holds the working rules; this file
> holds the map.

---

## 1. What CareerOS is

A single-user, locally-hosted job-application system. It discovers postings, scores them
against the candidate's profile and resume evidence, and then drives a real browser to fill
and submit application forms on ATS platforms (Greenhouse, Lever, Ashby, Workday,
SmartRecruiters and others). A human works the leftovers by hand.

The system is **single-tenant, single-process, and local-first**. There is one candidate,
one SQLite file, one browser profile, and one Autopilot runner.

---

## 2. Repo map

| Path | What it is |
|---|---|
| `apps/api` | FastAPI backend. Port **4000**. Owns all logic, state and automation. |
| `apps/web` | Next.js 15 / React 19 dashboard. Port **5000**. |
| `apps/extension` | Firefox/Chrome extension ("ApplyPilot") — content script autofill, IndexedDB, syncs to the API. Largely independent of the Autopilot path. |
| `packages/career-core` | Shared TS schemas, feature registry, roadmap data. |
| `packages/career-ui` | Shared React component library (`@career-os/ui`). |
| `apps/api/tests` | ~108 pytest files — the primary regression suite. |
| `apps/web/e2e` | Playwright specs (Firefox by default). |
| `apps/api/scripts`, `tools/` | Ad-hoc diagnostics and one-off operator scripts. Mostly untracked/experimental — **do not treat as API**. |
| `docs/` | Design notes and historical reports. Some are stale. |

Package manager is **pnpm** (workspaces). Python runs from **`apps/api/.venv/Scripts/python.exe`**.

---

## 3. Runtime topology

```
Browser ──► Next.js (:5000)
              │  app/api/backend/[...path]/route.ts  — transparent proxy,
              │  also guards the long-lived SSE stream against API reloads
              ▼
          FastAPI (:4000)  app/main.py
              │
              ├── AutopilotRunner        (singleton, in-process, owns the batch loop)
              ├── QueuePreprocessor      (singleton, scrapes + scores + enqueues)
              ├── Playwright worker      (own thread + event loop, owns the browser)
              ├── read_cache             (stale-while-revalidate for dashboard reads)
              └── SQLite  data/career_os.db
                     │
                     └── Ollama (:11434) — local LLM, auto-started by main.py
```

There are two supported ways to run this. The local Windows workflow
(`scripts/restart-dev.ps1`) is primary. `docker compose up` is an alternative that
containerizes **web** and **api** only — see `docs/docker.md`.

Two facts about the Docker topology that a future agent should not have to rediscover:
Playwright and Chromium live **inside the API image**, not in their own service, because
the API drives the browser in-process and the assisted-fill path's
`launch_persistent_context(..., channel="chrome")` cannot be driven over Playwright's
`connect()`. And there is **no database service**: the container bind-mounts the existing
`apps/api/data`, because CareerOS is SQLite (there is no MySQL in this repo, whatever a
task description may say). Ollama stays on the host, reached via `host.docker.internal`.

`main.py` is the whole process contract:
- **Refuses to start with >1 uvicorn worker** (`_warn_if_multi_worker`). All live state is
  module-level: browser sessions, task handles, the scrape task, the read cache. Override
  only with `CAREEROS_ALLOW_MULTI_WORKER=1`, and expect duplicate scrapes if you do.
- **Drains on shutdown** (`_drain_in_flight_work`): stops the runner, waits for anything in
  `APPLYING` to finish, cancels the scrape, closes the Playwright worker. A half-submitted
  application is the worst failure this system has.
- Starts Ollama in the background if it is not already reachable — but only when
  `careeros_ollama_health_url` still points at localhost. The liveness probes in
  `main.py`, `routers/diagnostic.py` and `services/observability.py` read that setting
  (`CAREEROS_OLLAMA_HEALTH_URL`, default unchanged at `http://127.0.0.1:11434`) rather
  than hardcoding the host, so a container can point them at the real Ollama.
- Middleware order matters: `AuthGateMiddleware` is registered *before* `CORSMiddleware` so
  CORS is the outer layer and a 401 still carries CORS headers.

---

## 4. Data and state

### Database — generic, not relational
`apps/api/app/db/store.py` defines exactly **two tables**:

- `KVStore` — key → JSON. Holds `profile`, `settings`, `resume_corpus_master`, snapshots,
  preprocessor stats.
- `EntityStore` — `(entity_type, id)` → JSON payload.

There are **no per-entity SQL tables**. Everything is a JSON blob keyed by an
`entity_type` string. The Autopilot types are declared at the top of
`services/application_assistant/persistence.py`:

```
aa_discovery_run · aa_discovered_job · aa_job_match · aa_application_draft
aa_answer_library · aa_browser_run · aa_autopilot_run · aa_autopilot_job
aa_application_claim
```

`aa_application_claim` is not a record type but a lock table: one row per posting
identity, holding the lease for the single in-flight attempt at that posting. Its
row id is a hash of the identity, so the primary key *is* the mutual exclusion
(see `claim_application_identity`).

Consequences an agent must internalise:
- Querying is `list_entities` + in-Python filtering, or `list_entities_where_json`. There
  are no joins and no schema migrations — shape changes are just new JSON keys.
- Reads over thousands of rows are expensive, which is why `services/read_cache.py` exists
  and why `persistence.py` maintains `AUTOPILOT_JOBS_CACHE_KEY` /
  `AUTOPILOT_STATS_CACHE_KEY` and invalidates them on write.

### Files on disk
- `apps/api/data/career_os.db` — the database.
- `apps/api/data/application_assistant/` — `screenshots/`, `field_screenshots/`,
  `tailored_resumes/`, `traces/`, `resume_uploads/`, `browser_profile/`, `chrome-profile/`.
- `apps/api/data/logs/api.log` — all logging, both the `career_os.*` and `careeros.*` trees.
- Job-discovery snapshot JSON under `CAREEROS_JOB_DISCOVER_DATA_DIR`.

**Never commit** any of it: credentials, browser sessions, resumes, application logs.

---

## 5. Core systems

### 5.1 Job discovery — `services/job_discover/`
Scrapes and aggregates postings from many sources, deduplicates, resolves aggregator
redirects to real ATS URLs, and scores relevance.

| Module | Owns |
|---|---|
| `scraper_service.py` (59 KB) | Source scrapers and the scrape loop. |
| `bigtech_scrapers.py` | Per-company careers-site scrapers. |
| `store.py` (55 KB) | Snapshot persistence, merge/prune, scoring, rescore orchestration. |
| `dedup.py` | Cross-source duplicate detection. |
| `aggregator_resolve.py`, `redirect_resolver.py`, `google_cse_resolver.py` | Turn aggregator links into canonical application URLs. |
| `relevancy_engine.py`, `role_classifier.py` | Is this posting the right kind of role? |
| `h1b_sponsorship.py` | Sponsorship signals. |
| `job_verification_engine.py`, `freshness.py` | Is the posting real and still live? |

### 5.2 Queue preprocessing — `services/application_assistant/queue_preprocessor.py`
A singleton background loop that keeps the Autopilot queue full. Each `_cycle`:
scrape if due → ingest the snapshot → find eligible unscored jobs → score them →
enqueue those that pass → re-rank the pending queue → periodically reconcile rejections.

Critically, `_application_in_flight()` makes it **back off while a submission is running** —
scoring loads a local model and would otherwise contend with the live browser.

Scoring goes through `mistral_resume_match.py` / `job_matching.py` and is gated by
`CAREEROS_LOCAL_LLM`. **An unscored job has no `matchScore` and is filtered out by the
run's minimum-match floor**, so turning the local model off stops new jobs entering the queue.

### 5.3 Autopilot run engine — `services/application_assistant/autopilot_runner.py` (124 KB)
`AutopilotRunner` is a singleton (`get_instance()`). Public surface: `start`, `pause`,
`stop`, `get_status`, plus an SSE event bus (`subscribe_events` / `_broadcast`).

Internals, in the order work flows:
- `_run_batch_worker` → `_process_batch_loop` → `_run_worker_slot` → `_process_single_job_with_retries`
  → `_execute_application_pipeline`.
- `_refill_queue` tops the queue up from the preprocessor.
- `_recover_stale_run_sync` recovers a run orphaned by a crash; job locks
  (`lockedBy` / `lockExpiresAt`) expire on their own, which is the crash-recovery path.
- `_trigger_post_batch_self_healing` hands failures to the Qwen self-healer after a batch.
- `_record_checkpoint` writes `CheckpointStep` history onto the job.

`_execute_application_pipeline` order (this is the sequence to reason about):
1. **Tier-1 guardrail** — dream companies are held for a hand-written application →
   `MANUAL_REVIEW` (reversible: `hasPersistentBlock` deliberately stays `False`).
2. **Hard filters** (`job_filter_ranker.evaluate_hard_filters`) against the profile.
   A rejection is passed to `ineligibility.classify_ineligibility`; a recognised permanent
   blocker becomes `INELIGIBLE` with a reason, anything unrecognised stays a soft `SKIPPED`.
3. Mark `APPLYING`, record `PAGE_OPENED`.
4. Load submission context (profile, answer library, master resume) — **on a worker thread**,
   because synchronous DB reads on the event loop were blocking the entire server.
5. Drive the browser, verify, receipt.

### 5.4 Browser automation — `playwright_autopilot_executor.py` (228 KB, the largest file)
Entry point `execute_live_playwright_submission`. Contains per-ATS fill strategies:
`_fill_all_greenhouse_comboboxes`, `_fill_ashby_fields`, `_advance_workday_to_form`,
`_fill_standard_and_react_fields`, `_select_react_combobox`, `_pick_location_option`,
plus DOM extraction (`_extract_dom_form_state`) and label sanitising.

Supporting cast:
- `browser_runner.py` — owns the Playwright worker thread and the persistent browser profile.
- `field_fill_engine.py` (67 KB) — generic DOM-aware fill; strategy chosen from live page state.
- `stealth_browser_profile.py`, `browser_fingerprint.py` — anti-detection profile setup.
- `browser_verifier.py`, `submission_watcher.py` — did the submission actually happen?
- `adaptive_browser_recovery.py`, `browser_replay.py` — recovery and replay.
- `ats_plugin_reference.py`, `greenhouse_schema.py`, `canonical_registry.py` — per-ATS knowledge.

### 5.5 Answer resolution — the chain that decides what goes in a field
```
question_classifier.py   label → semantic QuestionType
        ▼
profile_answer_resolver.py (97 KB)  THE single authoritative answer source
        ▼
structured_answer_engine.py / field_answers.py (57 KB)  → concrete value
        ▼
cross_field_validator.py · mapping_validation.py · submission_policy.py  → allowed?
```
`profile_answer_resolver.py` replaced scattered `if/elif` heuristics in the executor. New
answer logic belongs there, not in the executor. `llm_answer_generator.py` and
`semantic_field_resolution.py` are the fallbacks when the profile cannot answer directly;
anything still unresolved becomes an `unresolvedQuestions` entry and sends the job to
`NEEDS_REVIEW`.

### 5.6 Resume intelligence — `services/resume_intelligence/`
Retrieval-based tailoring over an evidence corpus, not keyword insertion.

| Module | Owns |
|---|---|
| `baseline_document.py` | The approved PDF as an immutable layout. **Only the server-configured `CAREEROS_APPROVED_RESUME_PATH` is ever opened** — a path in a request payload is never honoured. Unsupported layouts fail closed. |
| `minimal_tailoring.py` (40 KB) | `TailoringConfig` and conservative extractive slot selection. Holds `retrieval` mode (`fused` / `semantic` / `lexical`) and the BM25/RRF knobs. |
| `bm25.py`, `semantic.py`, `fusion.py` | Lexical index, embeddings, reciprocal rank fusion. |
| `local_composer.py` (29 KB) | CPU-only extractive composition. No model, no network, no invented claims. |
| `evidence_match.py`, `match_engine.py`, `ats_score.py` | Requirement → evidence matching and scoring. |
| `../story_index.py` (47 KB) | Technology→story index: retrieves only the evidence a JD needs, instead of stuffing every bullet into the prompt. |

Embeddings: **MiniLM is the default** (`CAREEROS_EMBEDDING_MODEL`, `bge` selectable).
Measured on this project's own 241 labelled queries, BGE and BM25+MiniLM fusion both scored
*worse* than MiniLM alone — see `scripts/matchlab/evidence_retrieval.py`. Weights are fetched
by `scripts/warm_embeddings.py`; `semantic.py` loads with `local_files_only=True` so a resume
request can never block on a download.

`resume_diff_service.py` computes the master-vs-tailored diff and renders the PDF.

### 5.7 Evidence, receipts and reconciliation
- `submission_receipt_service.py` — immutable receipt per submission: exact Q&A, pre-submit
  and confirmation screenshots, timestamps, submission hashes.
- `application_journey.py` — the per-job timeline the UI renders.
- `submission_outcome.py` — decides whether an unconfirmed attempt proved nothing was sent
  (`FAILED`, retryable) or left it unknown (`SUBMISSION_UNKNOWN`, never auto-retried). See
  the idempotency rules in §8.
- `manual_submission_reconciler.py` — marks a job `SUBMITTED` when its confirmation email
  arrives, so hand-completed applications do not depend on the user's memory. Reconciles
  forward only; it is evidence, never a trigger.
- `rejection_reconciler.py` — the same idea in reverse; moves `SUBMITTED` → `REJECTED`.
- `services/tracker/` + `services/gmail_imap.py` — Gmail reading and classification.

### 5.8 The Gemini layer — deliberately fenced in
`services/gemini/match_gate.py` states it plainly: it is **the only place a Gemini result is
allowed to influence an application**, and it is shaped so it can only ever be *more*
cautious than the deterministic path, never less. `gateway.py` handles transport, caching
and telemetry. Off in tests (`CAREEROS_GEMINI_ENABLED=0`, key blanked).

### 5.9 Self-healing and repair
- `autopilot_self_healer.py` — after a failed batch, collects diagnostics, reads executor
  source, asks Qwen for a targeted patch. `healing_response.py` validates the model's
  diagnosis before anything is trusted.
- `services/repair/` + `tools/repair-orchestrator` — a separate containerised repair loop.
- `services/observability.py` (30 KB), `error_fix_tracker.py`, `diagnostic_outcomes.py` —
  error history and the `/diagnostic` UI.

---

## 6. End-to-end flows

### Batch run (the main path)
```
QueuePreprocessor: scrape → dedup → score → enqueue (QUEUED)
        ▼  POST /autopilot/start
AutopilotRunner._process_batch_loop
        ▼  per job, sequentially
Tier-1 guard → hard filters → APPLYING → load context
        ▼
playwright_autopilot_executor: open → extract DOM → classify questions
        ▼
profile_answer_resolver → fill → validate
        ▼
submission_guard  (can this button be clicked at all?)
        ▼
verify (browser_verifier / submission_watcher) → receipt → SUBMITTED
        ▼
close_duplicate_applications(): every other record for the same URL is retired
```
Terminal alternatives at any stage: `NEEDS_REVIEW`, `MANUAL_REVIEW`, `SKIPPED`,
`INELIGIBLE`, `FAILED`.

### Single job
`POST /autopilot/jobs/{id}/reprocess` runs one job through the same pipeline. This is what
the UI's per-job retry buttons call (`reprocessSingleAutopilotJob` in
`lib/application-assistant-api.ts`).

### Review
Unresolved questions surface in `review-center.tsx`. Answering and approving feeds the
answer library and re-runs the job. `POST /autopilot/jobs/{id}/set-state` is the user's
manual bucket selector.

### Assisted fill
`POST /autopilot/jobs/{id}/assisted-fill` fills the form and **leaves the browser open** so
the user finishes and submits by hand.

---

## 7. Job status model

`services/application_assistant/domain.py` is the single source of truth for every enum.
The status lattice is the thing most likely to be got wrong:

| Status | Meaning | Who can finish it |
|---|---|---|
| `DISCOVERED` → `SCORED` → `QUEUED` | Pre-application pipeline | automation |
| `APPLYING` | In flight, holds a lease | automation |
| `STAGED` | Filled, awaiting approval | user approves |
| `NEEDS_REVIEW` | Open posting, automation can finish **once it has an answer** | user answers, automation continues |
| `MANUAL_REVIEW` | Open posting, automation will **never** finish it (CAPTCHA, undriveable form) | user, by hand |
| `SUBMITTED` / `REJECTED` | Sent / declined | — |
| `SUBMISSION_UNKNOWN` | Submit was clicked, no confirmation could be read — may or may not have been sent | **user only**; never retried automatically |
| `SKIPPED` | Soft filter; may pass later | automation, on retry |
| `INELIGIBLE` | Genuine dead end; always paired with an `IneligibilityReason` | nobody |
| `FAILED` | **Proven** not submitted — technical breakage before anything was sent | automation, on retry |

The organising question is **"can a human still land this application?"** If yes, it must not
sit in a terminal bucket. `IneligibilityReason` distinguishes real dead ends (expired,
not-a-real-posting, duplicate, citizenship-barred, outside the US) from operator policy
(`MANUAL_APPLICATION_REQUIRED` for Tier-1 companies, which is reversible).

---

## 8. Critical invariants

**Submission safety**
- `submission_guard.py` classifies every button before a click:
  `SAFE_NAVIGATION` / `MANUAL_ONLY` / `PROHIBITED`. Final-submit clicks require
  `ALLOW_REAL_SUBMISSION`; otherwise `SubmissionBlockedError`.
- Live e2e runs require `CAREEROS_LIVE_APPLY=1` plus an explicit comma-separated
  `CAREEROS_APPROVED_JOB_IDS` allowlist. Ordinary tests must never submit.
- **A changed button or an accepted request is not a submission.** Require the job's terminal
  state, the receipt, and confirmation evidence.
- Applications run **strictly sequentially**.
- On `SUBMITTED`, `close_duplicate_applications` must retire every other record for the same
  canonical application URL.

**Submission idempotency** (`submission_outcome.py`) — the rule that keeps one application
per posting:
- `FAILED` means *proven* not submitted, and is the only unconfirmed outcome that may be
  retried. Anything unproven is `SUBMISSION_UNKNOWN` and is never retried automatically.
- The deciding evidence is `submitAttemptedAt`, written durably by the executor's
  `on_submit_attempt` callback **immediately before the final click**. After that point
  nothing can prove the employer did not receive the form. The executor refuses to click if
  the marker cannot be persisted.
- The marker describes one attempt: it is cleared as each new attempt begins.
- Every duplicate guard passes `exclude_id=job["id"]`, so none of them protects a record
  against re-applying *itself* — that is exactly what this status split is for.
- A confirmation email is **later evidence**, never the authority on whether to send. It
  reconciles a record forward (`confirmedAt` / `confirmationSource`); a missing or late
  email never causes a reapplication. Confirmation is evidence on the record, not a separate
  status, so "still open = `SUBMITTED` − `REJECTED`" is unchanged.
- One in-flight attempt per posting is enforced in the database by
  `claim_application_identity`, keyed on `canonical_ats_posting_id`. `claim_job_lock` is a
  weaker guarantee — one worker per *record* — and several records routinely point at one
  posting.

**Truthfulness — these are not style preferences**
- Never fabricate an answer. If the profile does not hold the fact, the job goes to review.
- Never fuzzy-match a demographic self-identification onto a narrower option.
- Never defeat a CAPTCHA. Route to `MANUAL_REVIEW` instead.
- Never invent resume content. Evidence is authoritative; narrative text is a candidate for
  selection, not licence to synthesize.

**Process**
- One uvicorn worker. Always.
- Restarting the API must also kill spawned Playwright worker processes, or fixes appear to
  have no effect and memory leaks per restart (`scripts/restart-dev.ps1`).
- Do not run `next build` against the same `.next` directory while `next dev` is running.
- Bulk "reset to unapplied" must never sweep skipped, ineligible, manual-review or submitted
  jobs back into the queue.

**Resource budget** — this runs on one laptop with a local model. Resume tailoring is off by
default; `CAREEROS_LOCAL_LLM` is a RAM-budget dial the user owns. Do not silently flip it
either way, and do not hard-code a match-score floor.

---

## 9. Testing

| Suite | Command | Notes |
|---|---|---|
| API | `cd apps/api && python -m pytest tests -q` | ~108 files. `conftest.py` redirects the DB, browser profile and job-discover data dir into a temp dir and forces Gemini off. |
| Web typecheck | `cd apps/web && node ../../node_modules/typescript/bin/tsc --noEmit` | Use this when the pnpm shim is unavailable. |
| Web e2e | `pnpm --filter @career-os/web test:e2e` | Playwright, **Firefox by default** (Chromium's process-per-tab OOMs this machine), `workers: 1`, base URL `:5000`. |
| Lint/type | `pnpm lint`, `pnpm typecheck`, `pnpm lint:python` (ruff), `pnpm typecheck:python` (mypy, advisory) | |
| CI | `node scripts/ci-run.mjs` | |

High-signal regression tests: `test_autopilot_run_handoff.py`,
`test_autopilot_tailoring_mode.py`, `test_healing_response.py`, `test_job_lock_atomicity.py`,
`test_duplicate_submission.py`, `test_submission_policy_contradiction.py`,
`test_submission_confirmation_evidence.py`, `test_minimal_tailoring.py`,
`test_question_classifier_regressions.py`.

---

## 10. Where to look first

| Task | Start here |
|---|---|
| A field is filled wrong | `profile_answer_resolver.py`, then `question_classifier.py` |
| A specific ATS form breaks | `playwright_autopilot_executor.py` (per-ATS `_fill_*`), `ats_plugin_reference.py` |
| Job stuck in the wrong bucket | `domain.py` enums, `ineligibility.py`, `job_filter_ranker.evaluate_hard_filters` |
| Run won't start / stalls | `autopilot_runner.py` (`start`, `_process_batch_loop`), then job lock fields |
| Queue is empty | `queue_preprocessor.py`, and check `CAREEROS_LOCAL_LLM` — unscored jobs are filtered out |
| Resume content is wrong | `minimal_tailoring.py`, `story_index.py`, `local_composer.py` |
| Resume PDF layout is wrong | `baseline_document.py`, `resume_diff_service.py` |
| Retrieval quality | `scripts/matchlab/evidence_retrieval.py` — **measure before changing** `semantic.py` |
| Dashboard slow / stale | `read_cache.py`, cache keys in `persistence.py` |
| New API endpoint | `routers/application_assistant/` (registered in `routers/application_assistant/__init__.py`, mounted in `main.py`) |
| Autopilot UI | `apps/web/components/application-assistant/autopilot/`; types in `job-types.ts`, display in `job-presentation.ts` |
| Frontend API calls | `apps/web/lib/application-assistant-api.ts` |
| Styling | `apps/web/app/design-language.css` for shared tokens; CSS modules per component |
| Did it really submit? | `submission_receipt_service.py`, `data/application_assistant/screenshots/`, then the Gmail confirmation |
| Duplicate application sent | `submission_outcome.py`, then the three unproven-outcome paths in `autopilot_runner.py` and the requeue guards in `routers/application_assistant/autopilot.py` |

---

## 11. Traps

- **`docs/architecture.md` is stale.** Ports and data model are both wrong there.
- **The executor is 228 KB and the runner is 124 KB.** Extract cohesive helpers rather than
  adding another responsibility; do not attempt unrelated rewrites while debugging a live run.
- **Module-level singletons everywhere.** `AutopilotRunner.get_instance()`,
  `QueuePreprocessor.get_instance()`, the Playwright worker, the read cache. None survive a
  second process.
- **The working tree is usually dirty** with untracked diagnostic scripts and application
  evidence that is real user work. Inspect before touching, never bulk-clean.
- **`apps/api/scripts/` and `tools/` are operator scratch**, not a supported interface. Many
  are one-offs from a single debugging session.
- **Drive the app through its own UI.** Reading the DB to verify or diagnose is fine; making
  something happen by writing to the DB or calling the API directly is not.
