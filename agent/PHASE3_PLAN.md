# Phase 3 completion plan

Written against the actual code, using `planning-and-task-breakdown`. Covers
the three items left open from `PRODUCTION_READINESS_PLAN.md`'s Phase 3: CI
required-status, error boundaries + empty states, and structured operational
logging.

## What the codebase actually has (read before planning, not assumed)

**CI (item 2).** `scripts/ci.ps1`/`ci.sh` mirror `.github/workflows/ci.yml`
exactly; a local `pre-push` hook now runs the fast jobs. What's missing is
GitHub-side: making the workflow a *required* status check is a branch-
protection setting, and `gh auth status` reports no authenticated session on
this machine. This is blocked on the user, not on more code.

**Error boundaries and empty states (item 3).** Checked all 23 routes under
`app/(app)/`: **0 have their own `error.tsx`** — only the app-wide
`app/error.tsx` exists, so every route's crash shows the same generic
"CareerOS hit an error" screen with no route context and no recovery specific
to what broke. 12 of 23 already have `loading.tsx` (Phase 2 work). Separately,
`components/ui/feedback.tsx` already exports a real `EmptyState` component —
**imported by zero files**. At least 8 components hand-roll their own ad hoc
"No matches yet" paragraph instead of using it — the exact parallel-surface
pattern already fixed once this session for loading skeletons
(`WorkspaceLoading`). The fix here is the same shape: one reusable piece,
wired everywhere, not 23 bespoke error pages.

**Structured operational logging (item 4).** The production-readiness doc's
framing ("you debug live runs by reading api.log") is stale. A real
observability layer already exists: `services/observability.py` (798 lines —
`OpenTelemetryTracer`, `AgentTraceRecord`/`LangSmithAgentTracker`,
`DiagnosticErrorStore`, `AlarmManager`, correlation context, PII redaction)
and a queryable API surface in `routers/diagnostic.py`: `/errors`, `/traces`,
`/agent-traces`, `/runs/{id}/timeline`, `/outcomes`, `/alarms`. `autopilot_runner.py`
already imports `tracer`, `agent_tracker`, `error_store`, and correlation
context. What's unverified is *coverage*: whether every step of a real
submission (claim → fill → submit → verify) actually emits a trace span and
is queryable end-to-end, or whether only some steps do. Task 3.1 below is
that verification, done before any new logging code is written — building a
second logging system on top of an unverified-but-real one would be the
overengineering step 6/7 of the global environment's own simplicity ladder
warns against.

## Task List

### Phase A: Error boundaries and empty states — DONE

**Task A1 — One reusable route error boundary.** ✅ Done.
Description: A single `RouteError` component (props: what to call the thing
that broke, a retry action, an optional "go to X instead" link) that every
route's own thin `error.tsx` renders, mirroring the `WorkspaceLoading`
pattern already used for loading states.
Acceptance criteria:
- [ ] `components/ui/route-error.tsx` exports one component covering the
      cases the current root `error.tsx` and any route-specific need share
- [ ] Root `app/error.tsx` itself is simplified to use it (proves the
      component covers the general case before rolling out per-route)
Verification: typecheck; visually confirm on one route via a forced throw.
Dependencies: None. Files: 2. Size: S.

**Task A2 — Per-route `error.tsx`.** ✅ Done — all 24 routes, proven live via a
disposable smoke-test route that forced a real render throw, then removed.
Original wording below (for the record):
~~Per-route `error.tsx` for the routes that actually differ from the
generic fallback.~~
Description: Not all 23 need a bespoke message — most genuinely have nothing
route-specific to say. Add a route-specific `error.tsx` (using `RouteError`)
only where the route has a distinct recovery action (e.g. Applications:
"return to the queue" vs. Settings: "your changes may not have saved").
Acceptance criteria:
- [ ] Every route under `app/(app)/` has *some* `error.tsx` (route-specific
      or the generic one explicitly re-exported, not silently inherited)
- [ ] No route's error copy claims a recovery action the route doesn't have
Verification: typecheck; spot check 3 routes by forcing a render error.
Dependencies: A1. Files: ~10-15 (thin per-route files). Size: M — if this
grows past a session, split by route group (Autopilot-adjacent vs. everything
else) rather than doing all 23 in one sitting.

**Task A3 — Wire the existing `EmptyState` component into real usages.** ✅ Done,
scope corrected from the original plan on inspection: only `minimal-dashboard.tsx`
was a genuine hand-rolled duplicate. `pipeline-kanban.tsx`'s inline version is a
legitimately different, space-constrained variant (a kanban column has nowhere
near the room `EmptyState`'s generous panel padding assumes) — left alone rather
than forced. `CorpusEmptyState` (7 usages in resume-corpus) turned out to be a
separate, already-consolidated component from the `@career-os/ui/corpus`
workspace package serving that subsystem's own distinct design language, not a
duplicate — also left alone. Original wording below (for the record):
~~Wire the existing `EmptyState` component into real usages.~~
Description: Replace the ad hoc "No matches yet" paragraphs already found
(minimal-dashboard.tsx, feedback.tsx call sites never made, the 6+
resume-corpus components) with the shared component. Not a rewrite of their
copy — same words, one implementation instead of eight.
Acceptance criteria:
- [ ] `components/ui/feedback.tsx`'s `EmptyState` has at least one real caller
- [ ] Every hand-rolled empty-state paragraph found in the audit is converted
      or explicitly left with a one-line reason (e.g. it needs a layout
      `EmptyState` doesn't support)
Verification: typecheck; visual check via an e2e route that renders an
intentionally-empty list.
Dependencies: None (independent of A1/A2). Files: ~8. Size: M.

**Checkpoint A:** typecheck clean, no regression in the e2e suite's existing
empty-state-adjacent specs, root error boundary still renders correctly.

### Phase B: Structured logging verification and gap-closing

**Task B1 — Verify actual trace coverage on one real submission attempt.** ✅
Done, without running a new job (the standing "do not run any job" rule holds):
checked a real, already-completed automated submission
(`apjob_d8d2b080…`, Calendly, `submissionSource: null` — genuinely
automated, not manually resolved) against the live `/diagnostic/*` endpoints.

Finding, verified rather than assumed: **the actual gap is persistence, not
coverage.** `error_store.record_error` and `agent_tracker.record_agent_call`
are both real, reachable calls in the submission path (read the call sites at
`autopilot_runner.py:1814` and `:2188`) — the instrumentation is correctly
wired. But a `grep` across all 798 lines of `observability.py` for every
database-write mechanism used elsewhere in this codebase (`session_scope`,
`upsert_entity`, `set_kv`, raw SQL) found **zero hits** — every store in that
file is memory-only, despite `OpenTelemetryTracer`'s own docstring claiming
"In-memory + persisted". Confirmed live: `/diagnostic/errors` returned
`{"total": 0}` on a dev server that had been running for hours, purely
because this session's restarts (8-10+, from ordinary code-change reloads)
wiped it every time. Separately, the actual step-by-step submission
checkpoints (`JOB_CLAIMED → PAGE_OPENED → FORM_DISCOVERED → … → SUBMITTED`)
were never the gap — those write to the job's own DB row via
`_record_checkpoint`/`save_autopilot_job` and already survive restarts fine.

**Task B2 — Persist `DiagnosticErrorStore`.** ✅ Done. Scoped down from "close
whatever gaps B1 finds" to specifically this, because it's the highest-value,
lowest-volume of the three in-memory stores (genuine failures, not routine
per-request spans) — `tracer`'s HTTP spans and `agent_tracker`'s LLM-call
records are left in-memory for now, as a deliberately separate task rather
than folded in here (see "Deferred" below).
Acceptance criteria:
- [x] `record_error` persists to the entity table (`diagnostic_error`),
      best-effort — a DB failure must not lose the in-memory record or block
      the code path reporting the error
- [x] API startup rehydrates the store from the database
      (`_restore_diagnostic_errors` in `main.py`, mirroring
      `_recover_stranded_applications`'s pattern)
- [x] A fresh `DiagnosticErrorStore` instance (exactly what a restart
      produces) can load back what an earlier instance recorded
Verification: `apps/api/tests/test_observability_persistence.py`, 4 new
tests, all passing — including one proving a DB-write failure doesn't lose
the in-memory entry or crash the caller. Full API suite re-run to confirm no
regression (see below).

**Checkpoint B:** `/traces` and `/errors` genuinely reflect a real submission
end-to-end, verified by inspection of the endpoint's own JSON output, not by
re-reading the source and assuming it fires.

## Deferred

- **Persisting `tracer` (OpenTelemetry spans) and `agent_tracker` (LLM-call
  records).** Real gaps, same root cause as `error_store`, deliberately not
  folded into B2: `tracer` alone caps at 2000 spans and most of what it holds
  is routine per-request HTTP spans (`GET /health` etc.) with little
  after-the-fact debugging value relative to their volume — persisting it
  wholesale would be exactly the kind of unscoped, unjustified addition the
  global environment's simplicity ladder warns against. If a real need shows
  up (e.g. wanting to see the tailoring-model latency trend across restarts),
  scope that specifically rather than persisting everything preemptively.
- **CI required-status (item 2, second half).** Still genuinely blocked: `gh
  auth status` reports no session, and there's no way to set GitHub branch
  protection without either that or the repo settings UI directly. The local
  pre-push hook (fast checks) is the part that was reachable without it.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| A2 balloons into a 23-file mega-task | Medium — breaks the "smallest reasonable change" rule | Split by route group; ship the highest-traffic routes (Applications, Dashboard, Jobs) first as a checkpoint |
| B1 finds the gap is large | Unknown until measured | That's the point of doing B1 before writing B2 — no guessing the size upfront |
| Item 2 (CI required-status) stays blocked all session | Low — hook already covers the local half | Hand the user the exact GitHub-side steps rather than attempting a workaround |

## Open questions

- Does the user want per-route error copy authored now, or is "every route has
  *an* error.tsx, even a thin passthrough to the generic one" sufficient for
  this pass, with distinct copy added opportunistically later?
- For CI required-status: `gh auth login` (interactive, the user runs it via
  `!gh auth login`), or set branch protection directly in the GitHub web UI?
  Either unblocks item 2; I can't do either without one of them.
