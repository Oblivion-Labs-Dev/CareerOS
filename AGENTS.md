# CareerOS working guide

## Start here
- Dashboard: `apps/web` (Next.js), port 5000. API: `apps/api` (FastAPI), port 4000.
- Use the existing API virtual environment: `apps/api/.venv/Scripts/python.exe`.
- Read `docs/architecture.md` for the wider system. Arsenal is a sibling repository; keep career logic here.
- Inspect the working tree before editing; local diagnostic scripts and application evidence may be untracked user work.

## Application flow
- UI: `apps/web/components/application-assistant/autopilot/`.
- Job types and display helpers: `job-types.ts`, `job-presentation.ts` in that directory.
- Single Apply endpoint: `apps/api/app/routers/application_assistant/tailoring_receipts.py`.
- Run scheduling and job lifecycle: `apps/api/app/services/application_assistant/autopilot_runner.py`.
- Browser interactions: `playwright_autopilot_executor.py` in the same service directory.
- Resume drafting/rendering: `resume_diff_service.py`; model diagnosis validation: `healing_response.py`.

## Verification
- API tests use an isolated temporary database and browser profile via `tests/conftest.py`.
- Focused regression tests: `test_autopilot_run_handoff.py`, `test_autopilot_tailoring_mode.py`, `test_healing_response.py`.
- From `apps/web`, typecheck with `node ../../node_modules/typescript/bin/tsc --noEmit` if the package-manager executable shim is unavailable.
- Ordinary UI tests must not submit real applications. The live runner requires `CAREEROS_LIVE_APPLY=1` and at least ten explicitly approved comma-separated `CAREEROS_APPROVED_JOB_IDS`. It stops at ten verified submissions; skipped, expired, review, and failed outcomes never count. Never add replacement recipients without approval.
- Run approved applications sequentially. A changed button or accepted request is not a submission: require the exact job's terminal state and receipt, then inspect confirmation evidence.
- Preserve the selected resume mode, duplicate-submission guards, and human review for unresolved answers. Never lower these merely to make a test pass.
- Never commit credentials, browser sessions, private resumes, or application logs.

## Evidence and UI
- Local artifacts: `apps/api/data/application_assistant/screenshots/` and `tailored_resumes/`.
- Do not run `next build` against the same `.next` directory while `next dev` is running.
- Shared visual rules live in `apps/web/app/design-language.css`; component-specific rules belong in CSS modules. Reuse theme tokens and honor reduced motion.
- Prefer extracting cohesive helpers and types over adding another responsibility to large modules. Avoid unrelated rewrites while debugging a live run.
