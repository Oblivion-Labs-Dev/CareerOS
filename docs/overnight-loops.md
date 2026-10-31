# Overnight loops

Two independent loops run beside the live Auto Apply worker. Neither one submits an
application, writes a job row, or touches the code the live worker is running.

| Loop | What it does | Cost per healthy check |
|---|---|---|
| **A: supervisor** | Every 30 min: reads `/autopilot/status`, resumes recoverable pauses through `POST /autopilot/start`, tracks new submissions/failures/reviews, requeues jobs fixed by a *live* fix | no tokens |
| **B: improver** | Groups FAILED / MANUAL_REVIEW / NEEDS_USER_INPUT jobs by root cause, fixes ONE code group at a time in its own git worktree, validates it, and promotes it to `prod-readiness` only while the worker is idle | one `claude -p` run per attempt, plus a Codex review for high-risk paths |

Code lives in `apps/api/app/services/overnight/`; tests in `apps/api/tests/test_overnight_loops.py`.

## Commands

From the repo root (PowerShell):

```powershell
scripts/overnight.ps1 start            # launch both loops detached
scripts/overnight.ps1 status           # locks, last decision, current fix, recent flags (JSON)
scripts/overnight.ps1 stop             # finish the current step, then exit
scripts/overnight.ps1 stop -Now        # end our loop processes now (improver cleans up on next start)
scripts/overnight.ps1 resume           # start again, keeping the session start time for the report
scripts/overnight.ps1 report           # rebuild the morning report and dashboard
scripts/overnight.ps1 groups           # print failure groups (read-only)
scripts/overnight.ps1 supervise-once   # one supervisor cycle, to inspect a decision
scripts/overnight.ps1 promote          # try promotion now (idle worker only)
scripts/overnight.ps1 mark-live overnight/fix-... -Note "merged to main, API restarted"
```

Or directly: `cd apps/api; python -m app.services.overnight <command>`. Options: `--db` (default: the
live API's DB, opened read-only), `--api` (default `http://127.0.0.1:4000/application-assistant`), `--interval`, and
`--auto-start` (off by default: the supervisor only resumes runs, it never starts a brand-new run
unless you allow it).

`stop` without `-Now` can take up to 25 minutes if the improver is in the middle of an agent run.

## Where to look

Everything is in `apps/api/data/overnight/`:

- `morning-report.md`: metrics since the session started, top remaining groups, risks, changes awaiting
  your approval, failed gates, branches and commits, LLM usage. Unknown numbers say "unknown".
- `dashboard.html`: the same data in three sections (Auto Apply, Improvement, Resources), refreshing every minute.
- `supervisor.log`, `improver.log`, `events.jsonl`: what each loop did and why. Flagged events need you.
- `supervisor.json`, `improver.json`, `groups.json`, `promotion.json`, `requeue.json`: state.
- `locks/`: one lock per loop. A lock whose process has died is reclaimed automatically.

## What the supervisor will and will not do

It resumes: a run paused for "queue empty" when the queue has jobs again (max 8 per night), a run paused
by an infrastructure error (max 3, with backoff), and a RUNNING run whose heartbeat is older than 15
minutes with no worker mid-application. It holds and flags: more than one API process, concurrency above 1,
a missing browser, an unknown pause reason, and any refusal from the API (for example the live-apply gate).
It never resumes a run you paused yourself, and never restarts the API.

## How a fix travels

1. **Attempt.** The improver picks the largest code group (at least 2 eligible jobs, at most 2 attempts per
   group), creates `overnight/fix-<group>-<time>` in its own worktree, and runs the agent there.
2. **Validate.** The diff must stay out of protected paths (secrets, CI, the overnight loops and gates
   themselves, conftest, the email sender), touch at most 20 files, and include a regression test. Then the
   changed tests, the submission-guard tests, the security-gate tests and the overnight tests must pass. A
   change to submission, autopilot runner or browser code also needs a Codex review with no blocking finding.
   Anything that fails is removed and recorded as blocked with the reason.
3. **Promote.** Only when the worker is idle (no active job, no worker mid-application, API reachable), the
   fix is cherry-picked in an integration worktree, the gates run again, idleness is re-checked, and
   `prod-readiness` is fast-forwarded. Promotion refuses `main`/`master` and a target with uncommitted changes.
4. **Go live (you).** The live API runs from the main checkout. Review the fix, merge it, restart the API,
   then run `mark-live <branch>`. Nothing is merged to main or restarted automatically.
5. **Requeue.** After `mark-live`, the supervisor requeues the group's jobs through
   `POST /autopilot/jobs/{id}/reprocess`, at most 25 per cycle and once per job per fix. Jobs that were
   submitted, may have been submitted (SUBMISSION_UNKNOWN), share a URL with a submitted job, or have unanswered
   questions are never requeued; jobs that need your answers stay in review.

## Safety summary

One worker per queue, enforced by the existing run lock plus the supervisor's process and concurrency checks.
No rate limits or site protections are bypassed: the supervisor only calls the same API routes the UI uses.
The improver also holds the evolution `engine.lock`, so it never overlaps the nightly evolution job, and waits
when free RAM is under 1.5 GB. Tests use fakes only; no model is called in tests.
