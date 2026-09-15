# Autopilot hardening worklist — 2026-09-15

Single tracked list of everything requested in the 2026-09-15 session, so nothing is dropped.
Incident detail and evidence live in `NIGHT_BATCH_DECISIONS.md`; this file is the checklist.

Status: **DONE** · **IN PROGRESS** · **TODO** · **BLOCKED** (why) · **DECISION** (needs the user) · **WON'T DO** (why)

---

## A. Overnight batch loop

| # | Item | Status |
|---|------|--------|
| A1 | Keep the loop running, checking in every 15–25 min until told to stop | IN PROGRESS: run `PAUSED` with 0 `QUEUED` (supply exhausted); restarts only when new rows queue |
| A2 | Deploy the pending queue-watermark/dedup fix | DONE: already live since the 07:52 restart |
| A3 | Recover from the 12:39 Windows Update reboot | DONE: servers, Chrome, run recovered; nothing submitted twice |
| A4 | Gmail-verify submissions | DONE: all 12 in the last 12h confirmed (flex, DoorDash, Zuora, Ondo, UJET, Chainguard, Esri ×6) |

## B. Reporting and diagnostics (user requests)

| # | Item | Status |
|---|------|--------|
| B1 | Report on the last 12 hours | DONE (in chat) |
| B2 | New page under Diagnostic: why jobs went to manual review / failed, how many, reasons | DONE: `/diagnostic/history`, `GET /diagnostic/outcomes`; verified live (12h: 11 submitted / 25 staged / 171 failed / 167 skipped, API 526 ms, 374 rows) |
| B3 | Configurable window, up to 30 days | DONE: presets 1h/12h/24h/7d/14d/30d + custom; >30d rejected (400) |
| B4 | Time taken per application | DONE: per-attempt duration (claim → outcome), avg/median/p90/longest per outcome, slowest attempts |
| B5 | Explain why manual review is so high | DONE: 387 "no application form" (175 Himalayas), 91 reCAPTCHA, 75 Roblox, 52 Workday, 26 DataDome, 25 hCaptcha, 19 Okta |
| B7 | Loosen job filters (user chose: SWE title variants, ambiguous US locations, allow outside US; Defense/ITAR kept) | DONE 16:55: passing postings 41 → 1,562 (434 US-tier); `profile.allowInternationalLocations = true`; 84 tests pass |
| B6 | "Pull at least 500 jobs into the queue" | Now reachable after B7 (1,562 eligible); previously: not reachable from current supply. The preprocessor already tries to fill to 500 every cycle; only new, filter-passing, non-duplicate postings can be added (1–3 per scrape today). Raising supply needs more sources or looser filters (Defense/ITAR ~1,029, non-US, non-SWE titles). |

## C. Part 1: event-loop-blocking audit (`autopilot_runner.py` per-job chain)

| # | Item | Status |
|---|------|--------|
| C1 | Inventory and rank sync DB/CPU work on the event loop | DONE (offline timing, read-only) |
| C2 | Confirm each candidate live with py-spy during real processing | BLOCKED: queue empty, nothing processing |
| C3 | Fix: `close_duplicate_applications` full-scan fallback inside every SUBMITTED save (`:2094` → `persistence.save_autopilot_job`), 168 ms median, 95% of submissions hit it | TODO: fix + test + individual deploy + extended `/health` monitoring |
| C4 | Fix: duplicate pre-check loads all SUBMITTED rows every job (`:1382-1384`), ~73 ms | TODO: same process, separate deploy |
| C5 | Remaining `session_scope()` blocks (~30; single-row reads/writes < 3 ms uncontended) | TODO: py-spy under load decides; document each |
| C6 | Durable "pause discovery, keep the run" mode (`_ensure_queue_preprocessor` restarts it every loop iteration) | TODO: persisted flag checked before restart |
| C7 | Restart-discipline lessons from today: in-flight check must fail closed; editing `app/` triggers uvicorn reload and `pnpm --parallel` then kills the web server too | TODO: update `restart-careeros-dev` skill |

## D. Part 2: Roblox

| # | Item | Status |
|---|------|--------|
| D1 | Did overnight Roblox hangs reach the `validityToken` path? | DONE: **no**. 13 signed-embed follows, all Esri/Formlabs/Datadog; every Roblox attempt timed out in `page.goto` on `careers.roblox.com` (60 s) |
| D2 | Live check on a fresh posting | DONE: real Chrome loads it; Apply opens `job-boards.greenhouse.io/embed/job_app?for=roblox&validityToken=…&token=8197260` |
| D3 | Where the token comes from | DONE: Greenhouse's public embed loader `boards.greenhouse.io/embed/job_board/js?for=roblox` defines `Grnhse.Settings.embedToken` itself; Roblox's HTML and app bundles don't contain it. Automation can read it from that loader without loading `careers.roblox.com` |
| D4 | Standalone repro of the automation page-load failure | DONE: **every** automated browser is refused by `careers.roblox.com`: executor config → `ERR_CONNECTION_RESET`; without `--disable-http2`, plain headless Chromium, and real Chrome headless with no flags → `ERR_HTTP2_PROTOCOL_ERROR`. `curl` and a person's Chrome load it. Greenhouse's hosted Roblox page also hangs in automation; only the embed form loads (reCAPTCHA present) |
| D5 | Route Roblox applications to the Greenhouse embed form | **WON'T DO**: Roblox rejects automated browsers at the network edge, so using another door to get around that is evading their bot detection. Roblox stays Manual Review (hand-apply). *(Correction: an earlier note here called this "a compatibility fix, not a protection bypass"; the D4 evidence showed that was wrong.)* |
| D6 | Make the Roblox hard-filter reason truthful ("careers.roblox.com refuses automated browsers; apply by hand") and remove the unused `_ROBLOX_TEST_EXCEPTION_URLS` carve-out | TODO: `app/` edit = restart; do in the next zero-APPLYING window |

## E. Part 3: production readiness

| # | Item | Status |
|---|------|--------|
| E1 | Test failures | IN PROGRESS: **17 failed / 750 passed / 6 skipped** (was 24). Failing: anduril greenhouse autopilot; application_assistant_core ×3; greenhouse URL resolution/mapping ×3; autopilot_run_handoff ×1; autopilot_tailoring_mode ×2; document_support ×1; manual_submission_reconciler ×4; phone_country ×1; question_classifier_regressions ×1 |
| E2 | `pytest` from `apps/api` collects stray root/`scripts` `test_*.py` files and aborts | TODO: set `testpaths = tests` |
| E3 | tzdata / "Career progress is unavailable" | TODO: verify (not in today's failure list) |
| E4 | Job table pagination / archival strategy (2,500+ rows) | TODO: assessment |
| E5 | Frontend render performance Phases 2–5 | TODO: assessment + plan |
| E6 | Session-local scheduling vs `/schedule` cloud routines | TODO: assessment |

## F. Manual review and failure recovery (legitimate routes only)

| # | Item | Status |
|---|------|--------|
| F1 | Failures by company across Needs Review / Manual Review / Failed | DONE |
| F2 | "No application form" on employer career sites (Coinbase 22, TikTok 14, ZoomInfo 11, Airbnb 6): follow the employer's published apply link or map to their own ATS board | TODO: test per site |
| F3 | Himalayas (175): official API exists but its `applicationLink` points back to Himalayas and robots.txt disallows `/apply`; resolve to the employer's own ATS board by company + title instead, or drop the source | TODO: measure match rate / DECISION |
| F4 | Hacker News "Who's hiring" threads (19) | WON'T AUTOMATE: no form; email/links only |
| F5 | Needs Review: required fields left blank (169): military status, end dates, citizenship status, essays | TODO: list top fields for profile/answer-library additions |
| F6 | Needs Review: second-opinion match gate (113) | DECISION |
| F7 | Riot Games watchdog at QUESTIONS_COMPLETED (15) | TODO: diagnose |
| F8 | Greenhouse emailed security-code step (Segment ×6) | DECISION |
| F9 | Low match scores submitted while tailoring is off (`minMatchScore` bypassed) | DECISION (from 11:00 entry) |
| F10 | Defeat or evade CAPTCHA / DataDome / hCaptcha / Turnstile / Himalayas challenge (Camoufox, nodriver, SeleniumBase UC, TLS impersonation, residential proxies, solver services) | **WON'T DO**: these are the sites' own anti-automation controls. Affected postings (OpenAI 51, Okta 19, ServiceNow/Bosch DataDome 17, Palantir 8, Cerebras 9, Datadog 9…) stay in Manual Review for hand-applying |
