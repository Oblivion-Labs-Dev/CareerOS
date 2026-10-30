# CareerOS production-readiness pass — 2026-10-30

Branch `prod-readiness` (worktree `../CareerOS-prod`, rebased onto `647482a`). Not deployed.
Every number below was measured in this pass; anything not measured is marked **not measured**.

## Production verdict: **NOT READY** for hosted/multi-user production · **READY WITH MINOR ISSUES** as the owner's single-user local tool

JWTs were forgeable and the login gate was off unless a password was set; both now fail closed
under `CAREEROS_ENV=production`. The second pass closed CSRF, CORS, rate-limit spoofing, SSRF
(server fetches and every browser request), the missing `Secure` flag, exception text in 500s,
the ungated live click in dev/test, and retrying a clicked application without proof it was
rejected. What still blocks hosting: DNS rebinding needs an egress firewall on the VM, the full
test suite has not completed a clean run on this branch (see Verification), and the 13
pre-existing failures. Measured duplicate postings: 0.

## Core workflow

| Stage | Status | Evidence |
|---|---|---|
| Resume → Profile | PASS (functional) · accuracy **not measured** | `test_resume_parser.py` passes in isolation, but 2 tests fail in full-suite order, which points to state leaking between tests. There is no labelled resume set, so extraction accuracy is unknown. |
| Missing questions | PASS | `/autopilot/readiness` groups 1,115 open questions from 4.6k review jobs. The runner refuses an unattended batch while profile gaps block it (`start()` pre-flight). |
| Auto Apply | PASS with caveats | 765 SUBMITTED in 30 days. 756 have a confirmed receipt and 762 an email confirmation. 0 duplicate postings. 79 SUBMISSION_UNKNOWN, never auto-retried. |
| Review | PASS, after fix | The Autopilot jobs list returned **HTTP 500** whenever a page held a SUBMITTED job. Fixed. |
| Result recording | PASS | Receipts, screenshots and email reconciliation are in place. |

## Measured metrics (live DB, read-only, last 30 days)

| Metric | Value |
|---|---|
| Attempts (browser opened the form) | 6,253 |
| Verified successful / attempted | **756 / 6,253 = 12.1%** |
| Human intervention rate (review, manual, unknown) | **72.0%** (3,694 MANUAL_REVIEW, 727 NEEDS_REVIEW, 79 SUBMISSION_UNKNOWN) |
| False success | **not measured**. Upper bound: 3 of 765 SUBMITTED have no email confirmation, and 9 have no confirmed receipt |
| Duplicate submissions | **0** postings with more than one sent record, all time |
| Median / p95 application wall time | 259 s / 303 s. This includes the deliberate 300 s gap between submissions, so it is not fill time |
| LLM calls per application, in the apply path | about 0.02 (128 classifier calls in 30 days) |
| LLM cost per application | **$0**. 0 paid-provider calls in 30 days |
| Background LLM | 24,519 local queue-scoring calls (qwen3:4b). **Only 137 succeeded (0.6%)**, about 40 h of compute, Oct 1–15. Stopped since then |
| Profile extraction / question resolution / field mapping accuracy | **not measured**. No labelled ground truth exists |

## What changed (each bug has a regression test that fails before the fix)

**Auto Apply correctness and duplicate prevention**
1. `/autopilot/jobs` returned a 500 on any page containing a SUBMITTED job. The cause was a function-local import, which made `get_kv` an unbound local.
2. Four requeue paths could put a SUBMITTED, REJECTED, APPLYING or UNKNOWN job back on the queue: per-job reprocess, staged approve, question-group answer, and Apply (preflight approve). Each job's duplicate guards exclude its own record, so that applied twice. All four now share `requeue_refusal_reason`.
3. `start()` cancelled a live batch loop after 1 s and ran stale-run recovery against the job in flight. Callers include Apply, self-heal and Start. The job was left stuck in APPLYING. `start()` now resumes in place, with a respawn guard.
4. The 300 s submission gap was waited out inside the 600 s watchdog, so real submissions timed out into SUBMISSION_UNKNOWN. The gap is now waited out before the browser opens, and the watchdog gets 60 s of headroom.
5. Assisted fill now takes the posting claim, so it cannot race the batch on the same posting.

**Security and privacy**

6. JWT signatures were never verified, so any user's session could be forged. Signature and expiry are now mandatory.
7. `CAREEROS_ENV=production` refuses to start without `CAREER_OS_ADMIN_PASSWORD` and `CAREER_OS_SESSION_SECRET`.
8. Greenhouse email verification codes and profile answer values are no longer written to `api.log` or the activity log.

**Honest telemetry and LLM cost**

9. Every tailoring attempt logged a fake 450/320-token Ollama call. It is now recorded as local, with no tokens.
10. The review-question classifier, the only model call that is on by default inside the pipeline, is now cached by issue and has a 30 s per-job budget. Past the budget it uses the deterministic fallback.

**Latency** (same output hash before and after, on real data)

| Endpoint | Before p50 | After p50 | Fix |
|---|---|---|---|
| `GET /autopilot/jobs` (Autopilot list) | **HTTP 500** | 658 ms | #1 |
| `GET /autopilot/readiness` (Autopilot page load) | 3,527 ms (p95 6,265) | 566 ms (p95 642) | Cheap overlap check before the O(n²) subject check |
| `GET /application-assistant/jobs` | 6,196 ms | 1,474 ms | N+1 match lookups replaced by one read |
| `GET /tracker/summary` (Dashboard, Profile) | 3,012 ms | ~600 ms in-process* | Count and load through the status index, not 12.6k JSON parses |

\*Measured in-process (2.57 s → 0.53–0.84 s). The HTTP benchmark ran before this fix.

**UI scope**

11. The sidebar now shows only the core flow: Dashboard, Autopilot, Browse Jobs, Diagnostic, Resume & Profile, Settings. Markets, HN Hiring and the "Disabled pages" list are hidden behind `NEXT_PUBLIC_CAREEROS_NAV=full`, which restores the previous nav exactly.
12. Two broken `/autopilot` links on the dashboard now point to `/applications`.

## Second pass (same day): hosting security, submission proof, real-application eval

**Submission proof.** After the click, only a known ATS confirmation URL (Greenhouse
`/confirmation`, Phenom `applythankyou?status=success`) or a confirmation phrase with no active
errors counts as success. Historically 747 confirmations came via the Greenhouse URL, all
email-confirmed, so none is lost; about 4 generic-URL ones (betterteam, pinpoint, recruitcrm)
would now wait for the email. A clicked job is only resubmittable when the page *conclusively*
showed rejection (same URL path, form and button still there, errors shown); otherwise it is
SUBMISSION_UNKNOWN, and every requeue path refuses it (43 such NEEDS_REVIEW jobs exist today).
In dev/test the executor refuses the live click on any non-loopback page unless
`CAREEROS_LIVE_APPLY=1`, before the submit marker is written.

**Attempt breakdown (30 days, 6,253 attempts).** 3,979 were never eligible (2,745 manual-apply
pages, 945 bot-protected boards, 233 expired). Verified per eligible attempt: 884 / 2,274 =
**38.9%**. By ATS: Greenhouse 701/1,073, Ashby 0/640 (562 marked bot-protected), Lever 0/160
(145 hCaptcha), Workday 1/795 (711 account or no form), Workable 0/84, Phenom 5/89. The
Oct 28 browser incident accounts for 710 of 792 BROWSER_CRASH entries (already fixed on main).

**Real-application dry-run eval** (12 historical jobs, never submitted: `CAREEROS_ENV=test`,
a refusing submit marker, and a private DB copy). "Ready" means the run reached the final click
and was stopped by the gate. Live sites, not fixtures.

| Job | ATS | Before | After | Root cause fixed |
|---|---|---|---|---|
| Harvey | Ashby | false bot wall | **ready** (14 s) | `_systemfield_*` inputs not seen as a form, so a present-but-hidden reCAPTCHA read as a wall; "Legal First and Last Name" checked as a surname |
| Xsolla | Lever | false hCaptcha wall | **ready** (18 s) | Lever form not detected; `.application-label` text unread; name-only fields never healed; a select on "Select..." read as filled |
| Revstar | Workable | needs input | **ready** (16 s) | label read as `QA_12649654`; name-only field never filled; "Databricks Certifications" answered YES as an accuracy attestation |
| Fiserv (control) | Phenom | "no Next button" | already applied | employer's `status=alreadyApplied` page was misreported; now "Already applied" |
| Mastercard | Phenom | stuck at step 1 | step 4: 2 compliance questions | genuinely needs the owner |
| Purpose Financial | SuccessFactors | submit not found | account required | sign-in page rendered late and its email box passed as a form; re-checked before submit (without it, the test shows "Sign In" clicked as submit) |
| Colab | Greenhouse | needs input | needs input | 4 open-ended questions; approved answers only |
| Apex | Breezy | account | account | correct |
| Blue Origin | Workday | account | account | correct |
| Amazon | own site | no form | no form | correct |
| Affirm | Greenhouse | mismatch | expired | posting removed since |
| Natera (control) | Greenhouse | ready (123 s) | **not re-run** | after-pass stopped by low memory |

Before: 1 ready, 10 needing a human, median 23.5 s. After (10 of 12 re-run in the batch, Fiserv
probed separately): 3 ready, 6 needing a human, 1 expired, 0 browser errors, median 17.5 s.
Also fixed: the native-select pass was the only fill pass that volunteered optional
race/gender/veteran answers. Field-mapping and question-resolution accuracy are **not
measured** as percentages: no labelled answer key was built.

**Codex review** (run `20261030T204811-review-33a0e6`): one finding, confirmed and fixed. The
browser guard resolved names only for navigations, so a page's `<img>`/`fetch()` to an
internally-resolving name went through. DNS rebinding remains (the browser resolves again on
connect): firewall private ranges for the browser on a hosted box.

## Verification

- New and touched suites pass: submit path 116, hosting security 23, pacing 15, eval fixes 18,
  classifier/resolver/answer 581 (1 known failure). 12 of the eval-fix tests fail on unmodified
  main; the sign-in test fails with its new check removed.
- **Full suite: not completed on the final tree.** The last run reached 86% with only the 11
  known pre-existing failures, then hung for 240 s in the Playwright worker's event-loop
  shutdown (`browser_runner.shutdown_playwright_worker` -> `loop.close()`), and was later
  stopped by low system memory. Whether that hang is pre-existing is **unknown**.
- CPU/RAM under a real browser run: **not measured** (profiler written, not run).

## Features

- **KEEP:** Dashboard, Autopilot (`/applications`: queue, review, submitted), Resume & Profile with the setup wizard, Browse Jobs, Settings, Diagnostic (operator), Answer Bank.
- **HIDDEN (flag):** Markets, HN Hiring. These were already disabled and unclickable, and are now removed from the core nav: Inbox, Pipeline, All Applications, Review Center, Analytics, Resume Intelligence, AI Answers, Networking, LLM Benchmarks, Dummy Job Test Bed, Integrations.
- **REMOVE LATER** (still routable by URL, not in nav): the legacy `/application-assistant` dashboard. It duplicates `/applications`, and its `pending-fields/aggregate?use_ai=true` call takes 17–32 s. Also: `/benchmarks/*`, `/dev/*`, `/roadmap`, `/intelligence/signals|tasks`, `/apply/*`, `/job-search-portals`, `/u/[slug]`, the dead LLM paths (`structured_answer_engine.resolve_application_question`, `resume_diff_service._complete_batch*`), and the unused `qwen_form_reviewer` client build.

## Cost / hosting

The current architecture is one process and SQLite. Its browser state is process-local and it
requires a single uvicorn worker. Serverless (Vercel, Cloudflare Workers) cannot run the API or
the Playwright worker. Neon or Supabase would mean rewriting the store and gains nothing for one
user.

| | 10 apps/day | 100 apps/day | 500 apps/day |
|---|---|---|---|
| Hosting: one Oracle Always Free A1 VM running web, API, Playwright and SQLite | $0 | $0 | **not reachable as configured** |
| Database: SQLite on the VM's block volume (612 MB today) | $0 | $0 | $0 |
| Bandwidth and storage (screenshots, receipts) | $0 | $0 | $0 |
| LLM: deterministic path, local model off | $0 | $0 | $0 |
| TLS / ingress: Cloudflare free (DNS and Tunnel) | $0 | $0 | $0 |

- **What prevents 500 per day is policy, not price.** Runs are sequential with a 300 s minimum gap between submissions, which caps throughput at 288 submissions a day. Getting to 500 needs an owner decision on the gap or on concurrency.
- **Pricing to verify manually.** Oracle's A1 allowance is reported as cut from 4 OCPU / 24 GB to 2 OCPU / 12 GB ([linuxiac](https://linuxiac.com/?p=214114)); older guides still say 4/24. Check your tenancy limits. Cloudflare Workers Free gives 100k requests/day and unlimited static assets ([docs](https://developers.cloudflare.com/workers/platform/limits)). Render's free tier sleeps after 15 minutes, Railway Hobby is $5/mo, Fly.io has no free tier for new orgs ([comparison](https://findstack.com/resources/railway-vs-render-vs-fly-io)). Neon gives 0.5 GB free and Supabase 500 MB with a 7-day pause ([Neon](https://neon.com/guides/neon-vs-supabase-free-plan)). None of these were verified against the vendors' own pricing pages.
- **ARM caveat.** Assisted fill uses `channel="chrome"`. Google Chrome has no Linux ARM64 build, so on an A1 VM assisted fill needs bundled Chromium, and a visible window is not possible on a server.

## Remaining risks (genuine)

- **DNS rebinding** against the browser guard (see Codex review). Needs an egress firewall when hosted.
- **Full suite unverified on the final tree**, and a possible shutdown hang in the Playwright worker.
- **Job lock overwritten.** `claim_job_lock`'s lock fields are overwritten by the runner's next whole-payload save. The posting claim still holds.
- **Full-table JSON scans** in the duplicate and company-cap checks (`is_strict_duplicate_processed`). These cost per job and grow with history.
- **Test debt:** 13 pre-existing failures at `0c30b64`. 10 are in `test_company_cap_pacing.py` and 1 is the how-heard fallback, both from in-flight work committed in `0c30b64`. The other 2 are order-dependent resume-parser tests.

## Final architecture

```
Browser ──HTTPS──► Cloudflare (free DNS/Tunnel)
                        │
             ┌──────────▼───────────── one VM (Oracle A1 free, or the laptop) ─┐
             │  Next.js :5000  ──/api/backend proxy──►  FastAPI :4000 (1 worker) │
             │                                          ├─ AutopilotRunner (seq.) │
             │                                          ├─ Playwright Chromium    │
             │                                          └─ SQLite + files on disk │
             └──────────────────────────────────────────────────────────────────┘
                 (Ollama optional, off by default; no paid LLM on the apply path)
```

## Launch checklist

1. Set `CAREEROS_ENV=production`, `CAREER_OS_ADMIN_PASSWORD` and `CAREER_OS_SESSION_SECRET`.
2. Set `CAREER_OS_TRUSTED_PROXIES` to the reverse proxy's CIDR, and firewall private ranges for the browser.
3. Run the full suite to completion on this branch and settle the shutdown hang.
4. Re-run the Natera/Fiserv controls and Revstar dry runs; profile CPU/RAM on a 2 OCPU / 12 GB shape.
5. Keep `CAREEROS_LOCAL_LLM` off for queue scoring: 0.6% success measured.
6. Remove the legacy `/application-assistant` page and the dead LLM paths.
7. Fix or quarantine the 13 pre-existing test failures so CI is green.
8. Encrypt the backups; move `backups/encrypted/*` out of the public repo.
