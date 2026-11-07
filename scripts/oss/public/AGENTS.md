# CareerOS Agent Guide

Instructions for coding agents (Claude Code, Codex, Cursor and similar) and for human
contributors. `CONTRIBUTING.md` covers the workflow; this file covers how to change the code
safely.

## Repository guide

* Dashboard: `apps/web` (Next.js), port 5000.
* API: `apps/api` (FastAPI), port 4000.
* Development: `pnpm dev`. Everyday use: `docker compose -f docker-compose.prod.yml up -d --build`.
* Python: the API virtual environment in `apps/api/.venv` (created by `setup.sh` / `setup.bat`).
* Architecture: `docs/architecture.md`.

Application flow:

* UI: `apps/web/components/application-assistant/autopilot/`
* Apply endpoint: `apps/api/app/routers/application_assistant/tailoring_receipts.py`
* Scheduling and job lifecycle: `apps/api/app/services/application_assistant/autopilot_runner.py`
* Browser interaction: `playwright_autopilot_executor.py`
* Final-submit gate: `submission_guard.py`
* Matching: `role_shape_match.py`, `profile_match.py`, `ranking_preferences.py`

## Working rules

* Keep changes focused. Unrelated findings go into a separate issue.
* Extend what exists instead of adding a parallel system.
* Every reproducible bug gets a regression test that fails before the fix.
* Tests reach state through production code paths, not hand-made states production cannot produce.
* Never weaken a test, timeout or safety check to make something pass; fix the cause.
* Never fabricate data. Unknown values stay visibly unknown (`null`, "unknown"), never a guess.
* Errors must be loud: log, raise or show them. Never swallow a failure silently.
* Tests never call paid or hosted model APIs; use the fakes in `apps/api/tests`.

## Testing

* `cd apps/api && python -m pytest tests -m "not network"`. Tests use an isolated temporary
  database and browser profile through `tests/conftest.py`.
* Web typecheck: from `apps/web`, `node ../../node_modules/typescript/bin/tsc --noEmit`.
* UI changes: check them in the running app, in light and dark mode, and attach a screenshot to
  the pull request.

## Application safety

CareerOS acts on real job applications, so these rules are not optional:

* Tests must never submit a real application or send a real email.
* The only submission paths are the gated Autopilot runner and the user's own Apply. Never submit
  from backend code or ad-hoc scripts.
* The final Submit click is refused unless the user set `ALLOW_REAL_SUBMISSION=true`. Keep that
  default off.
* Skipped, expired, review and failed outcomes never count as submissions. A clicked button or an
  accepted HTTP request is not proof; require the job's terminal state and confirmation evidence.
* Never invent or guess an answer to an application question. Unsupported, sensitive or ambiguous
  questions go to human review.

## AI behaviour

When changing prompts, models or model-driven decisions: name the behaviour that could regress,
add or update a test, check grounding and ambiguity handling, and never treat model output alone
as proof of correctness. Everything must keep working with no `GEMINI_API_KEY` set.

## Sensitive data

Never commit credentials, API keys, browser sessions, resumes, application logs or anything under
`apps/api/data/`.
