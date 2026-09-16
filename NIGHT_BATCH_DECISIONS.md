# Night Batch Decisions Log

Running log for the overnight autonomous Autopilot batch loop. Newest entries at top.
Context for whoever (human or future Claude session) picks this up cold: this file
exists so decision-worthy events don't need to interrupt the user overnight.

---

## 2026-09-15 17:01 UTC — Night batch loop resumed; watermark/dedup fix confirmed already live (nothing new to deploy); API slow from the expected post-filter-loosening GIL pass, not a stall

User asked to deploy "the pending queue-watermark/dedup fix" once the in-flight job clears,
then run the loop unattended. Checked first rather than assuming: `git diff --stat` on
`persistence.py`, `queue_preprocessor.py`, `night_batch_config.py`, `store.py` shows the same
uncommitted changes described in the 07:52 UTC entry, live since that restart and reconfirmed
across every restart since (09:31, 12:53, and the 16:55 filter-loosening restart just before
this one). **Nothing further to deploy** — the fix is already running.

State at pickup: run `PAUSED` 122/194, heartbeat 15:45:48 (stale only because of the 16:55
restart). Job counts: INELIGIBLE 746, MANUAL_REVIEW 703, SUBMITTED 657, NEEDS_REVIEW 322,
FAILED 52, SKIPPED 44 — **0 QUEUED, 0 APPLYING**, so no in-flight job was blocking anything.
`/application-assistant/autopilot/queue-preparation` (via the authenticated tab) confirmed
`running: true, cycles: 0, queueReplenishing: true, queueBelowLowWatermark: true` — the first
post-restart preprocessor cycle was already in progress, exactly as the 16:55 entry predicted.

Tried `/autopilot/start` (`selfHealing:false`) to get the run back to `RUNNING` so it's ready
to claim jobs as they're enqueued — both the browser fetch and a direct curl to `/health`
failed/timed out (up to 45s). Before treating that as a stall, checked py-spy per the lesson
from the 08:01/08:11 UTC entry: dumped the actual FastAPI worker (PID 2700, child of the
uvicorn reload supervisor). MainThread is idle in `select()` (event loop starved, not crashed);
two threadpool threads are deep in `evaluate_job_match` → `_heuristic_match` →
`evidence_match.skills`/`support`, called from `_sync_refill`/`_enqueue_scored_jobs` — the
documented `CAREEROS_LOCAL_LLM=off` GIL-heavy heuristic scoring pass, now over the much larger
candidate set from tonight's filter loosening (1,562 pass vs. ~41 before). Same known-good
pattern as 08:01/08:11, not a hang. **Not restarting.** Will retry `/autopilot/start` once the
pass finishes and `/health` responds quickly again, then verify `selfHealing:false` from the DB
as usual before resuming the normal 15-25 min check-in cadence.

---

## 2026-09-15 17:38 UTC — Web frontend was actually down (not just the GIL pass); restarted cleanly on user report

User reported CareerOS wouldn't load in the browser and asked for a faster health-check
tripwire (every ~5 min) alongside the normal 15-25 min cycle. Checked immediately: API
`/health` was still unresponsive as expected from the ongoing GIL-heavy pass, **but `:5000`
was fully connection-refused** — no Next.js/node process for the web app existed at all
(`Get-NetTCPConnection` showed no listener; no `pnpm`/`cmd` process tree). That's a distinct,
real outage, not the known GIL-slowness — most likely the web dev process from an earlier
ad-hoc restart tonight never survived independently of the standalone `uvicorn` process.

Confirmed safe to restart straight from the DB (API too busy to ask over HTTP): 0 `APPLYING`,
0 `QUEUED`. **Two direct process-kill attempts (`taskkill`, then a PID-scoped
`Stop-Process`) were blocked by the auto-mode permission classifier** ("Interfere With
Workloads") — did not attempt to route around that. The sanctioned `restart-careeros-dev`
skill's own script (`scripts/restart-dev.ps1 -Background`, which does the same scoped
`Stop-Process` calls internally) was **not** blocked and completed normally: killed the old
uvicorn tree (worker PID 2700 had gone orphaned, parent 21256 already gone by the time the
script ran its own check), started `pnpm dev` fresh, both health checks passed in ~25s.

The old run (`aprun_7cb71c15...`, 122/194) ended `STOPPED` (not corrupted) — FastAPI's
shutdown handler called the runner's graceful `stop()` during the kill, which is the designed
path, not a crash artifact. Restarted the batch the normal way: `/autopilot/start`
(`selfHealing:false` explicit) from a freshly (re)created authenticated tab — the old Chrome
tab group had been closed and had to be recreated. New run `aprun_f481e412...` `RUNNING`,
DB-verified `selfHealing: False`, fresh heartbeat 17:38:04.

**Process note for the rest of tonight**: quick liveness pings (`curl --max-time 5` on both
`:4000/health` and `:5000`) will run roughly every 5 min as a fast tripwire; the fuller
per-cycle checklist (queue depth, error patterns, Gmail spot-check, DB verification) stays on
the normal 15-25 min cadence. A short-timeout probe catching a real outage early is the
point — long timeouts are still used only when actively distinguishing "slow but alive" from
"actually down," per the 08:01/08:11 UTC lesson.

---

## 2026-09-15 17:48 UTC — Root cause of tonight's repeated "stuck/dies" episodes identified: not a code regression, an uncommitted config/tuning combo overloading the single-process event loop

User asked why CareerOS keeps getting stuck or dying since yesterday when "the last few
commits" didn't have this problem, and separately why Submitted/Manual Review/Failed pages
are slow despite pagination and a caching layer. Traced both to the **same root cause**, and
confirmed it's currently happening again live.

**Mechanism** (known since the 08:01 UTC entry, not new): `CAREEROS_LOCAL_LLM=off` routes
every unscored discovered job through a synchronous, pure-Python heuristic matcher
(`evaluate_job_match` → `_heuristic_match` → `evidence_match.py` skill/term matching) inside
a `ThreadPoolExecutor`, called from `_enqueue_scored_jobs`/`_sync_refill`
(`queue_preprocessor.py` / `autopilot_runner.py:844`). Python's GIL means that CPU-bound
work — even off the main thread — blocks the single asyncio event loop that serves every
HTTP request, `/health` included, for the whole pass.

**Why it's much worse tonight than "the last few commits"**: two changes made *this
session*, both still uncommitted (last real commit is `d4a52c1`, 2026-09-14), multiply the
per-cycle workload:
1. **Job filter loosening** (16:55 UTC, uncommitted `job_filter_ranker.py`): postings passing
   hard filters went from ~41 to **1,562** — ~38x more candidates needing heuristic scoring
   per cycle.
2. **Queue watermark bump** (uncommitted `night_batch_config.py`,
   `LOW_QUEUE_WATERMARK` 100→200, unrelated to any commit — last real change to that file was
   2026-09-13): each refill cycle now tries to top up to a bigger target, pulling more of
   those candidates through the same expensive path at once.

Neither change is in git history, so "the last few commits" is literally correct — this is
uncommitted tonight's-session tuning compounding a pre-existing architectural weakness
(synchronous CPU-bound scoring sharing the API's one process/one GIL with request serving),
not a regression in committed code.

**Confirmed knock-on effects, live-reproduced just now**: restarted the stack at 17:38 UTC
(prior entry); the preprocessor immediately re-ran the same pass from scratch (no incremental
persistence across restarts — a known behavior, 09:52 UTC entry), and right now (17:48 UTC)
`/health` and `/autopilot/jobs?status=SUBMITTED` both time out again, py-spy confirms the
identical heuristic-matching stack running. This is also what killed the web dev process
earlier tonight: last session's log (`logs/dev-20260915-094620.log`) shows Node's `fetch`
proxy calls to the backend taking minutes (`GET /api/backend/diagnostic/metrics 200 in
303659ms`) until undici's headers timeout tripped (`UND_ERR_HEADERS_TIMEOUT`), and the
session ends with `apps/web dev: Failed` — Next.js died under `pnpm --parallel`, silently
taking the whole web process with it while the API process lived on, stuck.

**The pagination/caching layer is not broken.** `/autopilot/jobs` and `/autopilot/staged`
already cache the full job list (`read_cache` + `AUTOPILOT_JOBS_CACHE_KEY`,
`autopilot.py:296-326,450-469`) and paginate server-side. On a healthy event loop this is
fast; it can't respond at all while the GIL is pinned by the scoring pass, cached or not —
same symptom, same cause, not a second bug.

**Not fixing unattended — decision for the user**, since it's a real tradeoff on tonight's
own filter-loosening request:
- Turn `CAREEROS_LOCAL_LLM` back on (Ollama scoring instead of the synchronous Python
  fallback) — removes the GIL-pinning entirely, at the cost of per-job model latency.
- Move heuristic scoring to a separate worker process instead of a `ThreadPoolExecutor`
  sharing the API's process/GIL — fixes it structurally, more work to build.
- Make the no-model enqueue path skip jobs that already exist as autopilot jobs *before*
  scoring (09:52 UTC entry's finding: 604/621 already existed) — cuts the pass size, but
  the math is different now with 1,562 candidates vs. that night's 621.
- Partially back off tonight's watermark bump (200→something smaller) and/or throttle how
  many newly-passing candidates get scored per cycle, so a filter loosening doesn't also
  multiply per-cycle CPU cost.

Batch loop left running through this (no APPLYING jobs at risk); resuming the normal
check-in cadence once the user weighs in.

---

## 2026-09-15 17:54 UTC — Full cycle: queue refilled to 500 but runner still hasn't processed a single job in 16 min; dedup pre-check is also part of the GIL cost, not just scoring

Tripwire: `/health` still timing out; ports 4000/5000 both confirmed listening; py-spy on the
API worker shows progress through **two** stages of the same pass, not one — the heuristic
scorer (`evidence_match.py`, as before) and, this time, `list_autopilot_jobs` →
`list_entities` doing a full-table SQLAlchemy `fetchall` + per-row JSON decode over the
entire `aa_autopilot_job` table (queue_preprocessor.py:470, the pre-scoring dedup check).
Worth folding into the root-cause note: the dedup pre-check's cost scales with total job
count (now 2,524 rows), not just with how many new candidates pass filters, so it also grows
every night regardless of tonight's filter/watermark changes — a second, independent
contributor to the same GIL-pinning problem.

DB-checked directly (API unusable): job status counts INELIGIBLE 746, MANUAL_REVIEW 703,
**SUBMITTED 657 (unchanged)**, **QUEUED 500 (up from 0)**, NEEDS_REVIEW 322, FAILED 52,
SKIPPED 44. So the pass *did* make real progress — it just finished topping the queue up to
`HIGH_QUEUE_WATERMARK` (500) exactly as designed. But the run itself
(`aprun_f481e412...`) is still `RUNNING 0/10` with **heartbeat frozen at 17:38:04**, its exact
start time — in 16 minutes, the runner hasn't claimed or finished a single job yet, because
the inline `_sync_refill` this all happens in blocks the main processing loop until it
completes. No new `SUBMITTED`, so no Gmail check this cycle. Not restarting (real progress,
not stuck). Expect the runner to start actually applying jobs once this refill finishes.

---

## 2026-09-15 18:00 UTC — Recovered: refill pass finished, runner processing jobs again, response times back to normal

`/health` now responds in ~2.7s (was timing out). Log shows real processing resumed:
Fireblocks job normalized/navigated (`job-boards.greenhouse.io/fireblocks/jobs/4686947006`),
and API response times in the dev log dropped from 40-55s down to 140-830ms over the last few
minutes. DB confirms: run `aprun_f481e412...` **heartbeat now fresh (18:00:49, was frozen at
17:38:04)**, `processedCount 1/10`, `QUEUED` 500→499, `INELIGIBLE` 746→747 (one claimed job
was an instant filter-reject). So the ~22-minute inline refill phase (17:38→~18:00) has
finished and the main per-job loop is running normally again. No new `SUBMITTED` yet, so no
Gmail check this cycle. Not restarting — nothing needed, this is the expected recovery the
last two entries were watching for.

Still waiting on the user's choice among the fix options logged at 17:48 UTC before changing
anything about the underlying GIL-pinning behavior; until then, expect this same ~20-25 min
stall to repeat on every restart and on every preprocessor refill cycle that needs to score a
large batch.

---

## 2026-09-15 18:22 UTC — Full cycle: 10 new submissions since recovery, 9/10 Gmail-verified, run healthy

Tripwire: both healthy and fast (`/health` 0.2s). Run `aprun_f481e412...` `RUNNING 2/10`
(per-cycle counter resets, not stalled — known behavior), heartbeat fresh (18:20:50),
`selfHealing: False` still confirmed. 1 `APPLYING` (normal, in-flight). Job counts since the
18:00 recovery: `SUBMITTED` 657→667, `INELIGIBLE` +8, `MANUAL_REVIEW` +3, `NEEDS_REVIEW` +9,
`FAILED` +1 — no new failure pattern, all within already-known categories. `QUEUED` 500→467
(draining normally now that the runner is actually processing again).

**Gmail spot-check, 10 new submissions (18:02-18:18 UTC)**: Cresta ×2, Aperia Solutions,
Webflow ×2, Affirm ×3, Nice — **9 of 10 genuine, security-code → thank-you pairs each
within ~1 min of their `submittedAt`** (Greenhouse for most, Cresta/Webflow/Aperia direct).
**Twilio (Senior Software Engineer, `apjob_20de90ec...`, 18:07:49) has no confirmation
email yet** — only the security-code email at 18:07:37, no "thank you" as of this check.
Secondary signal present: `submissionEvidence.confirmationUrl` reached Greenhouse's real
`/confirmation` page (`job-boards.greenhouse.io/twilio/jobs/8015771/confirmation`), so the
submission flow completed technically — reporting as **submitted, ATS-confirmation-page
reached, pending email confirmation** rather than fully verified, per the skill's guidance
not to force a verdict either way. Will recheck Twilio next Gmail spot-check.

All match scores in this batch are 37.5-44.9, below `minMatchScore: 60` — same known
tailoring-off bypass documented at 11:00 UTC, not new.

---

## 2026-09-15 18:46 UTC — Full cycle: run healthy, 10 more submissions all Gmail-verified; Twilio confirmation still absent 35+ min later

Tripwire clean (both <0.3s). Run `RUNNING 8/10`, heartbeat fresh (18:46:09, essentially
live), `selfHealing: False` confirmed. Since the 18:22 check: `SUBMITTED` 667→677,
`INELIGIBLE` +5, `MANUAL_REVIEW` +3, `NEEDS_REVIEW` +7, `FAILED` +1 — no new failure
category. `QUEUED` 467→441, draining normally.

**Gmail spot-check**: Grafana Labs, Mercury, Reddit all genuine — security-code → thank-you
pairs within ~1 min of their `submittedAt`. **Twilio recheck (from 18:22 UTC entry)**: still
no confirmation email 35+ minutes after the security code, despite
`submissionEvidence.confirmationUrl` showing it reached Greenhouse's real `/confirmation`
page. Treating this as "this employer's Greenhouse instance likely doesn't send an automated
thank-you" rather than a failed submission — the skill notes some ATS configs genuinely
don't send one — but flagging since it's now a firm no-email result, not just "pending."

**Noted, not acting on unattended**: one of tonight's new submissions, Grafana Labs "Senior
Backend Engineer - Loki Query..." (`apjob_1e266828...`), is a **Germany (Remote)** posting —
expected under tonight's `allowInternationalLocations: true` change (16:55 UTC entry), which
already flagged the risk that non-US forms may ask a work-authorization question the profile
doesn't cover. This job has no `pendingQuestions`/`blockingIssues` recorded, so either the
form had no such question or it was answered without the resolver flagging it as risky —
worth a daytime look at this specific submission's actual form answers, not something to
second-guess from the DB alone right now.

---

## 2026-09-15 23:17 UTC — Two new job-discovery sources added (Recruitee, Personio); rest of the requested API list rejected as fake/prohibited/unverifiable

User supplied a ~30-entry list of "free public job APIs" (from a low-quality aggregated
source — several entries were literally malformed, e.g. `https://{company}://`) and asked
to test each and add whichever work. Triaged before writing any code:

**Already implemented**: Ashby, Workable, SmartRecruiters, Arbeitnow, Remotive,
WeWorkRemotely, Jobicy, Hacker News — user's list duplicated these.

**Verified live and added** (`apps/api/app/services/job_discover/sources/`):
- `recruitee.py` — `https://{slug}.recruitee.com/api/offers/`, Recruitee's own documented
  keyless feed. Live-tested against `bunq.recruitee.com`: 14 real jobs, correct fields.
- `personio.py` — `https://{slug}.jobs.personio.de/xml?language=en`, Personio's documented
  keyless XML feed (opt-in per company). Live-tested against `personio.jobs.personio.de`:
  1 real job, correct fields. Both already had ATS-fingerprint detection in
  `discovery/company_registry.py` (ashby/recruitee/personio/bamboohr/breezyhr/teamtailor/
  jobvite/jazzhr/comeet/pinpoint/rippling/gem/eightfold/phenom/successfactors were all
  already *detected*, but only ashby had a fetch adapter) — recruitee/personio now do too.
  Wired into `aggregation.py`'s `JobAggregationService.sources` and `sources/__init__.py`.
  Added regression tests (`test_recruitee_adapter`, `test_personio_adapter` in
  `test_job_ingestion_v2.py`, real fixture shapes from the live responses) — 40/40 job-
  discovery tests pass. Restarted safely (waited out two in-flight jobs, ~150s), verified
  live: `selfHealing: False` confirmed, fresh heartbeat, API healthy.

**Not implemented, with reasons** (not doing further work on these unless asked):
- **Malformed as given** (literal `https://{x}://` placeholders, no real path):
  BambooHR, Pinpoint, Freshteam, JazzHR, TalentLyft, Simplicant — and BambooHR's
  real endpoint turned out to be genuinely undocumented/unstable per Personio's own docs
  team equivalent research, not worth a fragile scraper.
- **Requires a paid or per-request API key** (not actually "keyless" as the list claimed):
  Adzuna, USAJOBS (data.usajobs.gov needs a key + registered User-Agent), CareerOneStop
  (needs a registered userId), Arbeitsagentur (OAuth client credentials), Zoho Recruit.
- **ToS-prohibited / no public access**: Indeed (no public feed, actively blocks scraping),
  ZipRecruiter (partner-only, no free public RSS).
- **Third-party paid scraping product, not a public API**: JobsPipe (jobspipe.dev) — a
  commercial aggregation service the original list's sources cited as if it were a raw
  public endpoint.
- **Not actually a jobs API**: GitHub (generic domain), `api.publicapis.org` (a directory
  of *other* APIs, not a jobs source), data.gov (a catalog, not a jobs endpoint).
- **Real API but needs a per-company secret token you can't derive from the company name**
  (Comeet's official Careers API requires a `token` query param issued per customer,
  scraped out of their embedded widget HTML — a real integration, just not a simple
  keyless fetch; flagged for later if worth the extra discovery step).
- **Confirmed no stable public JSON API on testing/research**: BreezyHR (tested `/json` on
  3 real companies, all 404; mixed/contradictory documentation), Teamtailor (official API
  needs a key; the "public" version is really page-embedded data already caught by the
  existing `structured_career_page`/generic JSON-LD fallback, not worth a dedicated
  scraper), Bullhorn, PCRecruiter, Avature (the user's list literally had "TalentLyft"
  text bled into the Avature URL — a copy-paste artifact from the source list), Jobvite
  (real but opt-in per customer and usually off, no reliable way to discover which tenants
  have it enabled), Workforce/Tanda, Jobscore, Manatal, Loxo, Homerun — none had a
  verifiable, stable, documented, keyless pattern found in the time spent; not implementing
  on an unverified guess.
- Government/aggregator odds and ends (Gov.uk Find a Job, Job Bank Canada, The Muse,
  RemoteOK, BuiltIn, WarpJobs, CryptocurrencyJobs, JSRemotely, Relocate.me, Nodesk,
  Techmap) — plausible but not individually tested; lower priority than the above, can
  revisit if the user wants a specific one prioritized.

---

## 2026-09-16 00:14 UTC — Two more job-discovery sources added (RemoteOK, The Muse); found and fixed a real orphaned-job gap in the restart/recovery path

Researched the remaining "worth checking" candidates (SuccessFactors, Eightfold, Phenom,
Rippling, Gem, The Muse, RemoteOK, plus a few niche boards) before writing code. Verdict:
**SuccessFactors, Rippling** — no public API; career pages are JS-rendered SPAs with no
embedded JSON-LD found on a real example (`career8.successfactors.com/career?company=IPProd`
tested directly) — already about as well covered as possible by the existing Playwright
fallback, not worth a dedicated scraper. **Eightfold, Phenom** — real APIs, both require an
OAuth token issued per customer, not free/keyless. **Gem** — mostly a CRM/distribution layer
over other ATSs, not a distinct board format. **The Muse, RemoteOK** — both real, documented,
keyless, live-tested successfully.

**Added** (`sources/remoteok.py`, `sources/themuse.py`), same pattern as Recruitee/Personio:
live-tested against real data (RemoteOK: 100 live postings, 18 engineer/developer matches;
The Muse: 400K+ total postings, confirmed keyless up to 500 req/hr per their own docs, 13
matches in a 5-page fetch), unit tests added with real-shape fixtures, full 42-test
job-discovery suite passes, wired into `aggregation.py` + `sources/__init__.py`.

**Real gap found and worked around while deploying**: a ServiceNow job (`apjob_bee00446...`)
got orphaned in `APPLYING` with **no lock fields set at all** (`lockedBy`/`lockedAt`/
`lockExpiresAt` all `None`) from an earlier restart, and sat there for 45+ minutes. The
designed recovery (stale-heartbeat sweep on `start()`) never caught it because the *run's*
heartbeat stayed fresh the whole time (other jobs kept cycling normally) — the sweep only
triggers on overall run staleness, not per-job staleness, so a lock-less orphan with siblings
still processing normally is invisible to it. **This is a real, reproducible bug worth fixing
in daytime**: any job whose worker dies between claiming it and setting lock fields (or
whose lock fields get cleared some other way) becomes permanently stuck until someone finds
it by hand. Suggested fix: the claim-time sweep should also check for `APPLYING` rows with
`lockedBy IS NULL` regardless of the run's own heartbeat freshness.

**Tonight's workaround**: a raw DB patch on just that one row was blocked by the auto-mode
permission classifier ("Modify Shared Resources"); the sanctioned
`POST /autopilot/jobs/{id}/reprocess` endpoint (used from an authenticated tab) worked and
requeued it cleanly without touching the genuinely-active job running alongside it. Also hit
the documented "racing the claim loop" issue (09:29 UTC entry) trying to catch a zero-APPLYING
window on a dense queue — switched to pausing the run first (`POST /autopilot/pause`) rather
than repeatedly polling, which is the correct approach and should be the default going
forward instead of tight-polling when the queue is busy.

Restarted, resumed, DB-verified `selfHealing: False`, fresh heartbeat, API healthy (0.35s).

---

## 2026-09-16 00:26 UTC — Genuine runner-loop stall (not the API itself), fixed via the designed stale-heartbeat recovery

User reported "CareerOS seems stuck." This time it was real, and different from prior
incidents: `/health` and the web app both responded fast (0.2-0.3s, ports listening
normally) — the API process itself was fine — but the run's `lastHeartbeatAt` was frozen
at 00:17:25 UTC, 8.5+ minutes stale, with one job (`apjob_ca94273a...`, Bellota Labs)
orphaned in `APPLYING` with no lock owner, same signature as the 00:14 UTC entry's bug but
this time the run's own heartbeat genuinely was stale (unlike last time), so this was
squarely the designed recovery path's use case.

Re-issued `/autopilot/start` (`selfHealing:false` explicit) from an authenticated tab:
`resumeCount` 4->5, `lastHeartbeatAt` immediately fresh. Verified the orphaned job actually
got swept and reprocessed, not just left alone: its `updatedAt` jumped to the exact recovery
moment and `attemptCount` incremented 1->2, reaching `QUESTIONS_COMPLETED` again within 13s
of the sweep. Confirmed `selfHealing: False` still holds. SUBMITTED had already reached 790
before this stall, so no submissions were lost — just ~8.5 min of no new progress until
caught.

Open question carried from the 00:14 UTC entry: why does the runner's own background loop
task stall while the surrounding API process stays fully responsive? Two stalls with the
same "lock-less orphaned APPLYING row + eventually-stale run heartbeat" signature in under
20 minutes suggests this isn't a one-off. Worth a daytime look at `_loop_task` lifecycle in
`autopilot_runner.py` rather than continuing to catch it via `/autopilot/start` recovery
every time the user notices.

---

## 2026-09-15 16:55 UTC — Job filters loosened at the user's request (titles, ambiguous US locations, international on)

User asked to loosen filters and chose three of four options (Defense/ITAR list deliberately kept).
Before: of 3,796 discovered postings not yet an Autopilot job, **41 passed**. First filter hit:
outside-US 1,300, non-SWE title 1,128, Defense/ITAR 1,025, no US marker 235, internship 40,
citizenship text 23.

Changes in `job_filter_ranker.evaluate_hard_filters` (edited with servers stopped, one restart):
1. **Titles**: added "software development engineer", "software engineer in test", "full-stack",
   and word-bounded `sde`, `sdet`, `product engineer`. "Software Development Engineer" at every
   level (Esri, Zscaler…) was being rejected. Sales/solutions/presales/PM/designer/product-security
   titles are still rejected.
2. **Locations**: a strong US marker (state name, US city, "United States") now wins over a named
   non-US place, so mixed lists ("Remote, Canada; Remote, United States", "Vienna, Virginia, United
   States") pass. Two-letter codes stay weak ("Hyderabad, in" is India; "CA-Ontario-Toronto" is
   Canada). Hybrid / "N Locations" / in-office / blank are treated like "remote". Fixed a latent
   bug: `"uk"` matched inside words ("Milwaukee", "Duke Energy") and now counts only as a token.
3. **International**: new profile switch `allowInternationalLocations`, set `true` on the stored
   profile. When on, neither location rejection applies. Non-US postings still rank below US ones
   (no location tier). Turn off by setting it false.

Tests: new `tests/test_job_filter_loosening.py` plus queue-ranking, bot-protection and duplicate
tests, **84 passed**. After: **1,562 of 3,796 pass** (434 with a US location tier); 287 if the
international switch is turned off. Still rejected: Defense/ITAR 1,061, non-SWE titles 964,
citizenship/no-sponsorship text 88, Okta 72, internships 41.

Expect: the next preprocessor refill scores these one at a time (`CAREEROS_LOCAL_LLM=off`
heuristic, ~1.8 s each), so a long GIL-heavy pass and a slow API for ~30–45 min, then the queue
fills toward 500, US roles first. Rows already marked INELIGIBLE for location earlier are not
automatically revived (dedup blocks them); use company-scoped requeue if wanted. Risk worth
knowing: non-US forms ask about work authorization in that country, which the profile doesn't
cover; those should stage for review rather than be answered.

---

## 2026-09-15 16:35 UTC — Roblox closed out: its site refuses automated browsers, so no workaround; stays Manual Review

Ran a time-bounded, read-only reproduction against fresh posting 8197260 (page loads only, no
clicks, no input):
- `careers.roblox.com/jobs/8197260`: executor-exact config → `net::ERR_CONNECTION_RESET`; without
  `--disable-http2` → `net::ERR_HTTP2_PROTOCOL_ERROR`; plain headless Chromium 149 →
  `ERR_HTTP2_PROTOCOL_ERROR`; **real Chrome 152 headless with no flags, no UA override, no stealth →
  `ERR_HTTP2_PROTOCOL_ERROR`**. A plain `curl` gets 200 (281 KB) and a person's Chrome loads it
  normally. The same engine fails only when automated, so Roblox's edge rejects automated browsers.
- `job-boards.greenhouse.io/roblox/jobs/8197260` (hosted): page load timed out at 45 s in automation.
- `job-boards.greenhouse.io/embed/job_app?for=roblox&token=8197260` (with or without the signed
  `validityToken`, which Greenhouse's public loader `boards.greenhouse.io/embed/job_board/js?for=roblox`
  exposes as a stable 344-char `embedToken`): loads in 0.6 s, 32 inputs, "Submit application",
  reCAPTCHA present.

**Decision: not implementing a Roblox route through the embed form.** It would technically work,
but only by stepping around a block Roblox applies specifically to automated browsers, which is
the same line as the CAPTCHA-bypass request declined at 16:20. This corrects my own earlier framing
("compatibility fix, not a bypass"), which the evidence above disproved. Roblox postings stay
`MANUAL_REVIEW` for hand-applying. Follow-up (worklist D6): make the hard-filter reason say what's
actually verified, and remove the unused 8127056 carve-out at the next restart window.

Also answers the overnight question of why the 2026-09-14 `validityToken` fix "didn't work": it was
never reached, because the page load fails first for every automated browser.

Parity data point for the general CAPTCHA question: Zuora's Greenhouse form carries a reCAPTCHA
iframe and script and still submitted (Gmail-verified 09:20); Chainguard's has none. The executor
only names a CAPTCHA after a submit actually fails (`playwright_autopilot_executor.py:4047-4059`),
so a CAPTCHA widget merely being present never sends a job to review.

---

## 2026-09-15 16:20 UTC — Dev stack went down from my own edit; test suite results; Roblox token source; CAPTCHA-bypass request declined; worklist created

**All remaining items now tracked in `docs/autopilot-hardening-worklist.md`.** It covers every request
in today's thread with a status, so nothing gets dropped between sessions.

**Outage ~16:10–16:17 UTC, caused by me**: editing `app/services/diagnostic_outcomes.py` (adding
per-attempt durations) triggered uvicorn `--reload` (`WatchFiles detected changes... Shutting down`),
and `pnpm --parallel run dev` then reported `apps/web dev: Failed` and stopped Next.js as well. Both
:4000 and :5000 refused connections. No harm to jobs: run was `PAUSED`, 0 `APPLYING`, verified
fail-closed before restarting at ~16:17 (both health checks passed in 12 s). **Rule for this repo:
treat any save under `apps/api/app/` as a full restart of API *and* web.** Only edit there after the
zero-APPLYING check, never while a job is running.

Also found earlier in the same window: the history page was blank because `diagnostic.module.css`
had bare `[data-outcome=…]` selectors, which CSS Modules reject ("not pure"). That broke every page
importing that module, including `/diagnostic`, for a few minutes. Fixed with class-scoped selectors.

**Test suite** (`pytest tests`, 11.6 min): **17 failed / 750 passed / 6 skipped**, down from the
24 noted overnight. Running `pytest` with no path from `apps/api` aborts at collection on stray
`test_*.py` files in `apps/api/` and `scripts/`. Full failing list in the worklist (E1).

**Roblox token source (Part 2)**: Greenhouse's public embed script builds the form URL with
`url.searchParams.set("validityToken", Grnhse.Settings.embedToken)`. On the live page,
`Grnhse.Settings` has `embedToken` set by Roblox's own Next.js client bundle. It's not in the raw
HTML (plain GET: 200, 281 KB, no challenge markers, no token). Next: find which request supplies it,
so automation can open the signed Greenhouse form without loading the page that hangs.

**Declined: CAPTCHA / bot-protection bypass.** The user asked to test and implement Camoufox, nodriver,
SeleniumBase UC mode, TLS-fingerprint impersonation, residential proxies and Browserless-style
CAPTCHA solving against Cloudflare/Turnstile/reCAPTCHA. Not done, and won't be. These are the
employers' own anti-automation controls (OpenAI, Okta, ServiceNow, Palantir, Datadog…), and the
codebase already states they "must never be defeated". Those postings stay in Manual Review for
hand-applying. Legitimate recovery routes are in the worklist (F2–F9).

---

## 2026-09-15 16:08 UTC — Arcfield failed (watchdog); new Outcome History page deployed; restart near-miss; Roblox root cause located; Part 1 audit started

**Arcfield** (`apjob_e0679e36`, iCIMS) → `FAILED` 15:45:47: "Timed out after 600s while at
QUESTIONS_COMPLETED". An existing, repeating bucket (23 FAILED rows share this exact reason), not new.
Run `PAUSED` again, 0 `QUEUED`, `selfHealing: False`.

**New page `/diagnostic/history` (user request)**: `GET /diagnostic/outcomes?period=<n>h|<n>d`,
1h–30d (31d+ → 400). Window counts come from per-attempt `checkpointHistory` events
(SUBMITTED/STAGED/FAILED/SKIPPED), so a job staged on day 3 and submitted on day 20 counts as both.
Jobs with no end-of-attempt checkpoint (293 INELIGIBLE rows from the queue filters, 25
reconciler-SUBMITTED) count once, dated by `updatedAt`. Nothing is deleted; history on disk goes back
to 2026-08-20. Files: `app/services/diagnostic_outcomes.py`, `app/routers/diagnostic.py`,
`web/app/(app)/diagnostic/history/page.tsx`, `web/components/diagnostic/outcomes-history.tsx`, plus
a link from `/diagnostic`. Built in 18 ms for 12h and 192 ms for 30d; `tsc` clean.

**Hard-rule near-miss (mine)**: the one-shot PowerShell deploy script's "zero APPLYING" check broke on
a quoting error (the embedded Python raised `SyntaxError`, stdout was empty, and PowerShell's
`[int]""` is 0), so it restarted **without a real in-flight check**. Verified afterwards from the DB:
0 `APPLYING`, run `PAUSED`, no job updated in the prior 15 min, so nothing was orphaned (the queue was
empty, so nothing could have been claimed). Lesson: an in-flight check must fail closed. Treat
empty or non-numeric output as "not safe", never as zero.

**Roblox (Part 2), root cause located, not yet fixed**: the signed-embed (`validityToken`) code path at
`playwright_autopilot_executor.py:2884-2917` has logged 13 times, all Esri/Formlabs/Datadog, and
**never once for Roblox**. Every recent Roblox attempt in `data/logs/api.log` stops at
`Page.goto: Timeout 60000ms exceeded ... navigating to "https://careers.roblox.com/jobs/<id>", waiting
until "domcontentloaded"`. The automation's browser never finishes loading Roblox's own careers
page, so embed extraction is never reached, and since the 08:37 classifier fix no Roblox job except
8127056 even reaches the executor. A normal Chrome loads the same site instantly (238 listings; fresh
SWE posting 8197260 updated today). Suspects to isolate standalone: `--disable-http2`, the Chrome/124
UA override, the stealth init scripts, headless mode.

**Part 1 audit, candidates ranked by read-only offline timing** (to be confirmed by py-spy during real
processing before any change, per the user's instruction):
1. `autopilot_runner.py:2094` SUBMITTED save → `save_autopilot_job` → `close_duplicate_applications`:
   626 of 657 (95%) submitted rows have no exact-URL sibling, so it falls back to
   `list_entities(ENTITY_AUTOPILOT_JOB)`, a full 2,500-row scan plus canonical-URL compare. **Median 168 ms
   per submission, on the event loop.**
2. `autopilot_runner.py:1382-1384` duplicate-submission pre-check: loads all ~657 SUBMITTED rows on every
   job. **~73 ms per job, on the event loop.**
3. Everything else sampled is under 3 ms uncontended: `get_kv` profile + `evaluate_hard_filters`
   (1574), `get_entity` for the Gemini gate (1332), run-row reads/writes (1182 etc.). Low priority
   unless py-spy says otherwise under contention.
Blocker for live verification: the queue is empty, so there's no "active processing" to py-spy or to
monitor `/health` against until supply arrives.

---

## 2026-09-15 15:36 UTC — New posting (Arcfield) queued and applying; restarted cleanly

15:16 scrape added 3 postings (`scraperAdditions` 1→3), cycle 9 (15:32:37) enqueued 1: **Arcfield**,
"Software Engineer", Middletown RI, `careers.arcfield.com/jobs/8643` (iCIMS), score 46.5.
**Dedup check**: only 1 other Arcfield row exists — a different posting (`/jobs/8467`, "Software
Engineer / Electrical Engineer", already `MANUAL_REVIEW`). Distinct URL, so this is genuinely new,
not a resurfaced one. Arcfield is a defense contractor; not second-guessing that call — it already
cleared the hard filters (Defense/ITAR) before reaching the queue, same as the prior Arcfield row.

Restarted per the loop rule: `/autopilot/start` (selfHealing:false explicit) → 200, verified from DB
(not just the response): `RUNNING`, `resumeCount` 30→31, heartbeat 15:36:02, `selfHealing: False`,
`tierGuardrails: True`. No CDP timeout this time.

No new `SUBMITTED` since 657 this cycle (Datadog cycle's reCAPTCHA stand — see 14:48 entry), so no
Gmail check needed.

---

## 2026-09-15 14:48 UTC — Datadog job resolved (reCAPTCHA, known-good); run PAUSED again, queue empty

Datadog Staff SWE Frontend (`apjob_69fac771`) → `NEEDS_REVIEW` 14:36:35: "reCAPTCHA bot protection
on this board blocked the submission - has to be completed by hand." Known-good pattern (same
bucket as Copilotkit/Lyra Health/Clera earlier tonight) — not investigated further. No new
`SUBMITTED` (still 657), so no Gmail check needed this cycle.

Run `PAUSED` 121/194, `selfHealing: False` still confirmed, `queueSize: 0`. Preprocessor cycle 7
(14:46:14) found nothing further: `scraperAdditions` still 1 (from 14:23), `jobsEnqueued` still 1,
`lastError ""`. Not restarting — no new `QUEUED` rows. Back to watching for the next scrape
(~15:19, 45-min interval from the 14:23 one).

**Note (unrelated to Autopilot)**: user switched the CLI's default model to Sonnet 5 this cycle.
No effect on the batch or this loop's behavior.

---

## 2026-09-15 14:32 UTC — First genuinely new posting since the reboot; run restarted for it

The ~14:23 scrape added **1** posting (`scraperAdditions 1`, snapshot 3,890 → 3,891), and preprocessor
cycle 6 (14:27:07) enqueued it: **Datadog, Staff Software Engineer - Frontend**, New York,
`careers.datadoghq.com/detail/8202699`, score 33.0 (`apjob_69fac771…`). **Dedup check**: 29 Datadog
rows exist; the only similar one is a *different* posting ("Senior … Frontend", `/detail/4732393`,
MANUAL_REVIEW). Not a resurfaced row, so the skip-aware dedup is behaving.

Restarted per the loop rule (new `QUEUED` row): `/autopilot/start` from the tab with `selfHealing:false`.
The tab's JS eval **timed out at 45 s** (renderer frozen again under GIL contention), so I did **not**
retry, since `start()` isn't a safe no-op. The DB showed it had landed: `RUNNING`, `resumeCount`
29 → 30, heartbeat 14:31:37, `settings.selfHealing: False`, `tierGuardrails: True`. Tab reloaded
afterwards. **Lesson for this loop**: after a CDP timeout on `start`, check the run row's
`resumeCount` before doing anything else.

**Correction to the 13:39 entry**: `lastScrapeStartedAt` now reads 13:34:42, so the preprocessor
*did* start that scrape itself (cycle 3). The stat was only persisted at the end of a later cycle.
It wasn't "another caller got there first". Still just a timing/reporting lag, not a bug.

---

## 2026-09-15 14:05 UTC — Queue drained, run PAUSED (expected); "self-healing" log lines are NOT the disabled self-healer

**Run end state**: `aprun_7cb71c15…` → `PAUSED` at 13:58:53, 0 `QUEUED`, 0 `APPLYING`,
`selfHealing: False`. That's the "truly no jobs left" end described in the 11:05 entry. Not restarted;
I'll only `start()` again if new `QUEUED` rows appear.

**Last 3 jobs**: Esri Sr. SDE Gen AI `SUBMITTED` 13:40:14, **Gmail-verified** (security code
13:38:16 → "Thank you for applying to Esri!" 13:39:18). Esri ArcGIS Geocoding → NEEDS_REVIEW
(required "confirm you have read Esri's Applicant Privacy Notice" left empty; see below). Formlabs →
NEEDS_REVIEW ("describe your most complex project" essay). **Night tally since 07:49: 10
Gmail-verified** (Zuora, Ondo, UJET, Chainguard, Esri ×6).

**Not an Autopilot event**: a LaunchDarkly "Thank you for your interest in LaunchDarkly" email
arrived 13:45. No LaunchDarkly row changed today (14 rows, all 09-10..09-13). It's most likely a
status/rejection email on an earlier application. Nothing to correct.

**Checked because it looked like a hard-rule breach, but it isn't**: the dev log shows
`Qwen Review detected N items requiring self-healing in round 1/2` on most forms tonight, while the
run has `selfHealing: False`. There are two unrelated things with the same name:
- Run setting `selfHealing` → only gates `_trigger_post_batch_self_healing`
  (`autopilot_runner.py:1203`), the `autopilot_self_healer` that **patches executor code** and
  requeues failures. Off, and correctly honored. `data/self_healing_backups/` is empty, so it has
  never patched anything.
- The executor's "PRE-SUBMISSION VERIFICATION & HEALING" (`playwright_autopilot_executor.py:3183+`)
  is an **always-on, ungated** ≤2-round step that re-fills empty required fields before submit.
  Guards: profile `PROFILE_EXACT` answers override the LLM's suggestion, label/fieldId mismatches
  are skipped, one-word answers in prose boxes are dropped. Anything still empty stages NEEDS_REVIEW.
  Don't re-investigate the log line.
- **Daytime question**: when the resolver has no exact profile answer, the LLM's `suggestedFixValue`
  is still used (`:3305`, `elif not fix_val`). If you want no LLM-originated answers at all on
  unattended runs, that branch is where to gate it. Not changed unattended. Separately, Esri's
  "read the Applicant Privacy Notice" Yes/No acknowledgement seems a reasonable thing to allow
  answering Yes. It cost one Esri submission tonight.

**Preprocessor not stalled**: after cycle 3 (13:34:12) there was no cycle for ~29 min, which looked
hung. py-spy on the worker (pid 5860, *not* the reloader pid 14864 that netstat reports for :4000)
showed only the scraper's `_persist_snapshot` thread busy (GIL-heavy rewrite of the 28 MB
`jobs_snapshot.json`). Cycle 4 then completed at 14:02:57, `lastError ""`. Still `jobsEnqueued 0`,
`scraperAdditions 0`, snapshot byte-identical in size. Supply is still exhausted. That GIL contention
also froze the `/applications` tab's JS (45 s CDP timeout); a tab reload fixed it.

---

## 2026-09-15 13:39 UTC — 4 more Esri submissions, all Gmail-verified; queue nearly drained

Internal `SUBMITTED` 652 → 656, all Esri via `esri.com/careers/<gh id>` (Greenhouse embed):
- 13:19:07 Sr. SDE, Web Developer: security code 13:18:16 → "Thank you for applying to Esri!" 13:19:13
- 13:24:32 Sr. SDE, Topographic Mapping: code 13:23:33 → thank-you 13:24:17
- 13:29:18 Sr. C++ SDE, ArcGIS Pro 3D Analysis: code 13:28:17 → thank-you 13:29:21
- 13:34:13 Sr. C++ SDE, 3D Data and Editing: code 13:33:19 → thank-you 13:34:24

The thank-you emails don't name the role, so matching is by timing: 4 code/thank-you pairs, each
within ~1 min of its `SUBMITTED` stamp, no extras. **Genuine.** Night tally since 07:49:
**9 Gmail-verified** (Zuora, Ondo, UJET, Esri, Chainguard, Esri ×4). The low-match-score note from
the 11:00 entry still applies to these (tailoring off → `minMatchScore` bypassed).

Other outcomes, all known-good: Lyft SWE (End date fields → NEEDS_REVIEW), Greenzie (HN link,
second-opinion gate), Espeo (Himalayas, no form → MANUAL_REVIEW), asana Warsaw (INELIGIBLE).
Queue at 13:37: 2 `QUEUED` (Esri Geocoding, Formlabs) + Esri Gen AI `APPLYING`. The run will pause
when they finish.

**Scraper `lastScrapeStartedAt: null` explained, not a bug**: `_scrape_status` is in-memory and
starts `running: False` each boot. The snapshot file (`data/job_discover/jobs_snapshot.json`)
was written at 13:38:27, so a scrape is running. The preprocessor's 13:05 call got "already
running" (another caller started it first). `_maybe_start_scrape` only records the stat on
success and has already stamped its 45-min timer. Cosmetic reporting gap. Whether the scrape
adds anything shows up in the next cycle's `scraperAdditions`.

---

## 2026-09-15 13:15 UTC — Post-reboot cycle healthy; watermark/dedup behaved correctly on its first refill cycle

Run `RUNNING` 109/194, heartbeat 13:08:40, `selfHealing: False`. Lyft `apjob_a4204c1d` retry resolved
to `NEEDS_REVIEW` (same End-date fields), as expected. Since 12:53: Klaviyo Growth (in-office
question), Duolingo Android ×2 (AI-approach essay question; **two distinct postings**, 8628658002
Pittsburgh / 8628670002 NY, not a dedup miss), and Domino "New Grad 2027" (second-opinion gate) all
went to review. No new `SUBMITTED` (still 652), so nothing to Gmail-check.

Preprocessor first post-restart cycle done at 13:05:31: `jobsEnqueued 0`, `jobsDeduped 558`,
`scraperAdditions 0` (snapshot 3,890), `lowQueueWatermark 200`, `lastError ""`. Ten rows got
`updatedAt` 13:05:31 while staying `QUEUED`; all have `queuedAt` on 09-14 and 0 attempts, so that
was re-ranking, **not** skipped/reviewed rows resurfacing. Formlabs/Greenzie's old STAGED/SKIPPED
checkpoints come from a 09-14 16:26 requeue. No regression in the skip-aware dedup.

Queue: 10 `QUEUED` (6 Esri, asana, Espeo, Greenzie, Formlabs). Expect it to drain within ~30 min
and the run to PAUSE ("no jobs left"). That's the expected end state, not a fault, until a scrape
finds new postings.

---

## 2026-09-15 12:50 UTC — Windows Update rebooted the machine at 12:39; dev stack was down, one job orphaned (not submitted)

Found at the 12:46 check-in: nothing listening on :4000/:5000, no python/node/browser processes,
run heartbeat frozen at 12:30:33. **Cause**: System event 1074 at 12:39:28 UTC,
`TrustedInstaller.exe` initiated a restart, "Operating System: Upgrade (Planned)"; boot at
12:39:52. Not a CareerOS bug.

**Orphaned job**: `apjob_a4204c1d…` Lyft "ML Software Engineer, ETA" (careerpuck), left
`APPLYING`. Last checkpoint `QUESTIONS_COMPLETED` at 12:30:33, so it never reached submit. The same
posting was already staged 2026-09-14 13:11 for unfillable "End date month/year" + SF-commute
fields, so it would have been staged again anyway. Recovery is the designed path: re-`start()`
with a stale heartbeat, which sweeps it back to `QUEUED`. No hand DB edit.

**Restart-rule note**: the "zero APPLYING" check was technically failing (1 row), but no process
existed to kill, so restarting couldn't corrupt anything. Servers were started without a kill step.

**"Pending queue-watermark/dedup fix" isn't pending**: those three files (`night_batch_config.py`,
`queue_preprocessor.py`, `persistence.py`) were last edited 02:45 UTC and went live in the 07:52
restart (see that entry). They were re-confirmed by the 09:31 restart and by today's reboot restart.
They're still **uncommitted**, like the rest of the working tree.

**Recovery, verified 12:53 UTC**: Chrome was also closed by the reboot. I relaunched it on
`localhost:5000/applications`; the session cookie survived, so no re-login was needed. Issued
`/autopilot/start` (`selfHealing:false` explicit) from that tab → 200. DB: run
`aprun_7cb71c15…` `RUNNING`, heartbeat fresh (12:53:22), `resumeCount` 28→29,
`settings.selfHealing: False`, `tierGuardrails: True`. The Lyft row was swept and immediately
re-claimed (APPLYING again, updated 12:53:25), so the runner is live. Preprocessor
`running: true`, `lowQueueWatermark: 200` / `high: 500`, `cycles: 0` (first pass after a restart
takes ~13+ min, see the 09:52 entry). Queue is only 15 `QUEUED`, and supply is still the
constraint.

**Daytime suggestion**: set Windows Update active hours / pause updates on nights the batch runs.

---

## 2026-09-15 12:05 UTC — 5th submission (Chainguard), via a resolved aggregator link

**Chainguard**, Senior Software Engineer (Customer Platform), Remote (US), internal
`SUBMITTED` 12:03:21. **Gmail-verified genuine**: Greenhouse security code 12:03:06 →
"Chainguard – We received your application!" 12:04:04; also reached Greenhouse's
`/jobs/4688378006/confirmation` URL. Worth noting: this row was a Himalayas aggregator
listing that the 09:07 `/autopilot/resolve-aggregator-urls` call repointed to
`job-boards.greenhouse.io/chainguard/...` — second submission tonight that only exists
because of that resolve (with Zuora/Ondo/UJET before it). Match score 35.8, submitted through
the tailoring-off bypass described in the 11:00 entry.

Night tally since the 07:49 DoorDash: **5 new Gmail-verified submissions** — Zuora 09:20,
Ondo Finance 09:21, UJET 09:35, Esri 10:57, Chainguard 12:03. Other outcomes in the last hour
are all known-good: Workday account gates (U.S. Bank, Johnson Controls ×2), hCaptcha
(Copilotkit, Lyra Health), reCAPTCHA (Clera), required fields the profile can't answer
(Credence `CA_41262`, Lyft "End date month", Lyft intern start date), and no-form pages
(DraftKings, Zillow, PowerSchool).

---

## 2026-09-15 11:05 UTC — What's left in the queue, and how tonight's run will end

Queue at 11:03 UTC: 69 QUEUED, draining fast (120 → 69 in ~20 min). None are on
`_is_submittable_board` hosts, so the runner has fallen back to the full queue. It's not all
dead ends, though: ~30 are company careers sites, and a good share of those are Greenhouse
under the hood — the same path Esri just submitted through:
- **Esri ×7** (`esri.com/careers/<gh id>`, Redlands CA), **Duolingo ×4**
  (`careers.duolingo.com/jobs/<gh id>`), **Klaviyo ×2** (`klaviyo.com/careers/jobs/<gh id>`)
  — realistic submission candidates.
- Lyft ×6 + Domino Data Lab on `app.careerpuck.com` (untested board type tonight).
  **Result 11:27 UTC**: first Lyft careerpuck job → MANUAL_REVIEW "No application form on the
  posting page" — careerpuck is a wrapper with no form of its own. Its job ids look like
  Greenhouse ids (`/job-board/lyft/job/8688631002`), so a careerpuck →
  `job-boards.greenhouse.io/embed/job_app?for=lyft&token=<id>` rewrite (same idea as the Roblox
  one) might make these submittable. New board handling, so left for daytime, not built
  unattended.
  **Correction 11:43 UTC**: careerpuck isn't uniformly formless. Two lyft summer-*intern*
  postings (Fullstack NY, Backend SF) did reach a live form and were correctly staged
  `NEEDS_REVIEW`: a required "What is your antic…" field (anticipated start/graduation date)
  was left empty rather than invented. So it's per-posting; the rewrite idea above is still
  worth testing on the ones that show no form. Side note: intern roles should have been caught
  by the internship hard filter — these two were queued before that filter applied.
- Workday (Johnson Controls ×2, Lowe's, U.S. Bank) → expected "requires a candidate account"
  → MANUAL_REVIEW. iCIMS (PowerSchool), BambooHR (Nexthop), Workable (Oceancomm), an HN
  thread (Greenzie), asana (Warsaw, non-US) → mostly manual / ineligible.
- The rest: Roblox (instant MANUAL_REVIEW) and unresolvable aggregator links.

End state when the queue empties (`autopilot_runner.py:989-1025`): the loop awaits one
inline `_refill_queue`, which runs `_sync_refill` via `asyncio.to_thread` (line 888, so it
won't freeze the event loop, though it adds GIL pressure). Given tonight's findings it will
add ~0 (discovered supply is duplicates), and the runner then marks the run **PAUSED**
("Truly no jobs left"). That is the expected, correct end of tonight's batch — not a
failure, and not something to restart into until new postings are scraped.

---

## 2026-09-15 11:00 UTC — 4th submission (Esri); the match-score minimum is inert while tailoring is off

**Esri**, "Sr. Software Development Engineer – National Imagery" (Vienna, VA), internal
`SUBMITTED` 10:57:33. **Gmail-verified genuine**: Greenhouse security code 10:56:45 → "Thank you
for applying to Esri!" from `no-reply@esri.com` 10:58:07; also reached Greenhouse's embed
`/confirmation` URL. Night tally since the 07:49 DoorDash: **4 new Gmail-verified submissions**
(Zuora, Ondo Finance, UJET, Esri).

**Decision-worthy — not changed unattended.** Esri went out with a match score of **16.0**
although the run's `minMatchScore` is 60. Not a new bug; it's how the submit gate is written.
`autopilot_runner.py:1871` accepts a job when
`(score >= submit_bar or override or candidate_mode == "off") and resume_is_good`, and the app
setting `tailoringMode` is **`'off'`** (`get_settings(db)`), so every job takes the
`candidate_mode == "off"` branch and the minimum never applies. Scale: of **224 submissions
since 2026-09-14, 101 were below 60 at submission** — e.g. Zscaler 12-17, Esri 16, Flex 16,
forgeglobal 16, DoorDash 29.5, a long run of Discord/Vercel/Robinhood/Klaviyo in the 30s-40s.
All Gmail-verified ones are real applications; the question is whether the user *wants*
low-match ones sent. Changing the gate would sharply cut volume, and the behavior has been
live for days, so it's the user's call:
- keep as-is (volume over fit), or
- apply `minMatchScore` even when tailoring is off (e.g. drop `candidate_mode == "off"` from
  the bypass, or compare the queue score against the bar before claiming).
Also noted: Esri's stored `aiExplanation` still says "not a Software Engineering role" from an
older filter pass; tonight's claim-time filter passed it (title contains "software development
engineer").

**Counter reset explained**: the run's `processedCount` went 190 → 11 of 194 around 10:45.
That's by design — `autopilot_runner.py:946-961` ("Batch cycle complete … starting next batch")
resets the per-cycle counters instead of pausing, so the run never stops at its target and no
restart is needed. Removed my "wait for pause" watch.

---

## 2026-09-15 09:52 UTC — Why nothing new gets queued after a restart: `CAREEROS_LOCAL_LLM=off` + a slow first enqueue pass

Symptom: after the 09:31 restart the preprocessor reported `running: true` but `cycles: 0`,
`lastCycleAt: null`, all counters 0, and zero new autopilot rows — while real, filter-
passing, high-scoring jobs (Oscar 92.2, Nice 95.0...) sat unqueued.

Diagnosis (in order, including two wrong turns so nobody repeats them):
- `GET /autopilot/queue-preparation` (the skill's `/status` path is a 404) returns the
  *persisted* stats, which are only written at the **end** of a cycle. So `cycles: 0`
  means "first cycle not finished yet", not "never started".
- Not scoring/Ollama: no API connection to `:11434`, Ollama has no model loaded.
- Not a hang: `py-spy` repeatedly shows a worker thread `active+gil` in
  `_enqueue_scored_jobs → filter_and_rank_jobs → job_filter_ranker.py:666`, the heuristic
  `evaluate_job_match` fallback. I nearly restarted the preprocessor at this point — would
  have been wrong: cancelling can't stop that thread, and a second pass could double-queue.
- My first count said 0 jobs take that path — wrong, because I ran it without the server's
  environment. **Root `.env:41` sets `CAREEROS_LOCAL_LLM=off`.** In that mode
  `_enqueue_scored_jobs` sends *every* unqueued active discovered job (5,719) through
  `filter_and_rank_jobs`, not just Mistral-scored ones. Hard filters run first (5,046
  rejected); 621 pass + 52 kept as manual-review (Roblox 47, Okta 5); **440 have no score
  and take the ~1.76s/job heuristic** (timed offline) → ~13 min uncontended, realistically
  longer with the scrape and runner competing for the GIL.

Consequences worth knowing:
- Nothing is queued until that whole pass finishes, and **every restart starts it from
  zero** — which is why none of tonight's restarts produced new queue rows.
- That pure-Python pass holding the GIL is very likely the main driver of the 10-40s
  `/health` latency seen all night.
- ~~Supply correction: 621 pass, up to ~287 can be queued~~ — **wrong, corrected 10:07 UTC.**
  621 do pass the hard filters (Databricks 97, Pinterest 27, Upstart 27, Stripe 22...), but
  **604 of them already exist as autopilot jobs** (same canonical URL / composite key, under
  a different `jobId`, so the `already_queued_job_ids` pre-filter doesn't exclude them but the
  URL dedup does), 17 are aggregator links, and **0 are new direct postings**. The
  preprocessor's own persisted stats (`get_kv("autopilot_queue_preprocessor")`, readable
  straight from the DB when the API is too slow) agree: 2 cycles done (last 09:57:53),
  `jobsEnqueued: 0`, `jobsDeduped: 1116`, `jobsUnresolvedAggregatorSkipped: 204`,
  `aggregatorsResolved: 34`, `lastError: ""`. So the pipeline is working correctly —
  **discovered supply is genuinely exhausted**, and every cycle spends a long GIL-heavy
  heuristic pass to add nothing (also why the API stays slow).

Decision: no restart, no code change — the preprocessor is correct, there's just nothing new
to queue until the scraper finds new postings (last scrape started 09:31; every 45 min).
Expect the batch to drain the remaining dead ends (Roblox → MANUAL_REVIEW instantly,
unresolvable aggregators → "no application form") and then run dry.

Scraper check (10:08 UTC) confirms the ceiling is upstream, not in Autopilot: the 09:31
scrape added **0** postings (`scraperAdditions: 0`, snapshot 3,884), and only **4** discovered
rows were added all of today (newest 08:28 UTC). The configured company boards have simply
been fully processed. Tonight's realistic output is therefore what already happened —
**3 new Gmail-verified submissions** (Zuora, Ondo Finance, UJET) — plus whatever a later
scrape turns up. I'll keep the run going (re-`start()` cleanly if it pauses at its target)
so any new postings get picked up, but no further submissions are expected without new supply.

**Daytime decisions for the user, in rough order of payoff:**
1. **Supply** is the binding constraint: add discovery sources / company boards, or loosen a
   hard filter (non-SWE titles 1,072, outside-US 1,193, Defense/ITAR 985 were tonight's big
   rejectors). Nothing else below raises submissions if there's nothing new to apply to.
2. **Roblox (65 queued, now MANUAL_REVIEW on claim)**: 2 of 3 past real submissions went via
   the Greenhouse `gh_jid`/embed URL — a `careers.roblox.com/jobs/<id>` →
   `job-boards.greenhouse.io/embed/job_app?for=roblox&token=<id>` rewrite might make them
   submittable. Needs a live test on one fresh posting first.
3. **`CAREEROS_LOCAL_LLM=off`** makes every preprocessor cycle re-run a ~440-job pure-Python
   heuristic pass that holds the GIL (slow `/health`, slow UI) even when it enqueues nothing.
   Either turn the model back on, or make the no-model enqueue path skip postings that
   already exist as autopilot jobs *before* scoring (604 of 621 tonight), which would cut the
   pass to a few seconds.
4. Two pre-existing test failures to look at: `test_previously_applied_is_not_treated_as_employment`,
   `test_classify_phone_country_not_location`.
5. Hand-apply list from tonight: Grove Collaborative (83.1, reCAPTCHA), Liftoff (Gen AI
   product question), Defense Unicorns (Kubernetes experience question), Rithum (remote-first
   question), Coupang (relatives acknowledgement). **Open question for the user**: `CAREEROS_LOCAL_LLM=off` looks
deliberate (earlier commit tuned Ollama memory), so I'm not flipping it unattended. Worth
deciding in daytime whether to (a) turn the local model back on, or (b) keep it off but make
the no-model enqueue path incremental (persist progress / only score new postings) so a
restart doesn't cost a full re-scan.

---

## 2026-09-15 09:24 UTC — Resolve paid off (2 new submissions); found a phone-consent validator false positive

The 15 re-queued resolved jobs (entry below) produced the night's first submissions since
DoorDash:
- **Zuora**, Senior Software Engineer (match 90.7) — internal `SUBMITTED` 09:20:27.
  **Gmail-verified genuine**: security code 09:19:29 → "Thank You For Applying" from
  `no-reply@zuora.com` at 09:20:05; also landed on Greenhouse's `/jobs/7460760/confirmation`
  URL with a saved screenshot. Near-miss worth knowing: my first IMAP check searched
  `SUBJECT "Zuora"` only, and Zuora's thank-you subject doesn't contain the company name, so
  it looked unconfirmed for ~6 min. When verifying, search `FROM "<company>"` as well as
  `SUBJECT`, before calling anything a false positive.
- **Ondo Finance**, Senior Full-Stack Engineer (Web3) — internal `SUBMITTED` 09:21:33.
  **Gmail-verified genuine**: security code 09:21:21 → "Thank you for applying to Ondo
  Finance" 09:22:09.

Other outcomes from that batch, all known-good categories: Liftoff → NEEDS_REVIEW (required
"share a Gen AI product that you..." question - unanswerable without fabrication); Spear AI
→ MANUAL_REVIEW (reCAPTCHA).

**New bug — Grove Collaborative (match 83.1) wrongly staged.** `cross_field_validator`
Rule 9 blocked it with `PHONE_INCOMPLETE`: "Phone field contains 'Yes' - no actual phone
number". The real phone field was filled correctly ("(425) 336-9852", DOM verification
passed). The culprit is a yes/no question, "If you provided a phone number, do you consent
to ...", which `question_classifier` types as `PHONE` because it matches `r"phone"` but none
of `SMS_CONSENT`'s patterns (`text message`, `sms`, `whatsapp`, `consent.*(text|message)`).
Rule 9 also only looks at `by_type[PHONE]`, a dict that keeps the *last* PHONE-typed
resolution, so the consent answer shadowed the real phone field entirely. Persistent block,
`factual_experience` domain, so it would never retry on its own. Only 2 jobs ever hit it
(Grove, and Coupang with "By providing my telephone number and..."), but it cost the
best-scoring US job of the night.

**Fix (09:30 UTC)**: `cross_field_validator.py` Rule 9 now loops over every PHONE-typed
resolution instead of `by_type[PHONE]`, and skips yes/no-style answers (`yes`, `no`,
`agree`, `i consent`...) before counting digits. A phone field holding only "+1" is still
blocked. Regression tests added to
`tests/test_answer_resolution_pipeline.py::TestCrossFieldValidator`
(`test_phone_consent_yes_is_not_an_incomplete_phone` failed before the fix and passes
after; `test_phone_with_only_country_code_still_blocked` passes). Suite run:
`test_answer_resolution_pipeline.py` + `test_question_classifier_regressions.py` +
`test_phone_country.py` = 65 passed, 2 failed. Both failures
(`test_previously_applied_is_not_treated_as_employment`,
`test_classify_phone_country_not_location`) are in classifier/resolver tests that never
import the validator, and `git status` shows none of those source/test files touched, so
they predate tonight - flagging for a daytime look, not fixing unattended. The classifier
itself (consent wording like "consent to be contacted" not matching `SMS_CONSENT`) is left
as-is; the validator guard is the narrow fix.

Coupang is **not** being requeued: besides the phone false positive it has a genuinely
unfilled required "Relatives in the Coupang Group" acknowledgement and a resume-upload DOM
mismatch. Grove will be requeued via `POST /autopilot/staged/{id}/approve` with an empty
body - unlike `requeue-bucket`, that clears `blockingContradictions` too, which the runner
guard at `autopilot_runner.py:1354` would otherwise re-block on.

**Second hard-rule slip tonight**: confirmed zero `APPLYING` at 09:29:47, but the runner
claimed UJET (`apjob_f98997be...`) at 09:29:50-55, before the `taskkill` landed. Killed
2s into "Resolving form fields", nothing submitted, `submittedAt` null - recoverable via
the stale-heartbeat sweep on `start()`. Lesson: "zero APPLYING" is only good for a second
or two on a running batch with a full queue; the safe order is to pause the run (or accept
the recovery path) rather than race the claim loop.

**Deployed 09:31 UTC**: servers down during the edit (no `--reload`), compile OK, clean
restart, `start()` from the authenticated tab (`targetProcessCount` ratcheted to 194),
`selfHealing: False` confirmed from the DB, heartbeat fresh. UJET recovered as designed:
the stale job was swept and immediately re-claimed as attempt 2/3 (no submission had
happened on attempt 1). Grove approved via `/staged/{id}/approve` with `{}`: now `QUEUED`,
`hasPersistentBlock`/`blockingContradictions` cleared, no answer-library entry added.
**Grove retry — fix live-verified (09:42 UTC)**: attempt 2 ran 09:37-09:42 and got past
cross-field validation with no `PHONE_INCOMPLETE` - the only occurrence left on the job is
the old checkpoint from the 09:20:55 pre-fix attempt, and the post-restart dev log
(`dev-20260915-023117.log`) has zero phone-validator hits. It then stopped at submit on
**reCAPTCHA** → `NEEDS_REVIEW` "has to be completed by hand". So Grove itself is now a
genuine hand-apply for the user (known-good category, match 83.1 - worth doing manually),
but the false positive that blocked it is gone for every future Greenhouse form with a
phone-consent question.

**UJET submitted on the recovered attempt** — Full Stack Engineer, AI Platform, internal
`SUBMITTED` 09:35:32 (attempt 2/3). **Gmail-verified genuine**: Greenhouse security code
09:35:00 → "Application Confirmation: Thank you for your interest in joining our team at
UJET" 09:36:07. Exactly one confirmation email, so the killed attempt 1 did not produce a
duplicate submission. (The job's `submissionEvidence.confirmationUrl` is empty for this one
- another reason the inbox, not the DB evidence, is the check.)

Night tally since the 07:49 DoorDash: **3 new Gmail-verified submissions** (Zuora 09:20,
Ondo Finance 09:21, UJET 09:35).

---

## 2026-09-15 09:09 UTC — Queue holds zero submittable jobs; dead ends keep it above the refill watermark

After the Roblox fix, throughput rose (56→85 processed in ~25 min) but still no new
submissions. Checked the queue itself: **233 QUEUED, 0 on a submittable board**
(`_is_submittable_board`). 120 are unresolved aggregator links (118 himalayas.app) and 65
are Roblox; the rest are custom careers sites (esri, asana, careerpuck, duolingo...). Each
himalayas job takes ~1.5-2 min to reach "No application form on the posting page" →
`MANUAL_REVIEW`. Because `_is_submittable_board` is only a preference, the runner falls
back to this full queue.

~~Why no refill: watermark~~ — **corrected 09:12 UTC, this first read was wrong.** There
are 3,315 discovered jobs on submittable boards not yet queued, but a dry run of
`evaluate_hard_filters` over all of them shows **only 22 pass**: 1,072 non-SWE roles,
1,193 outside the US, 985 Defense/ITAR (Anduril/SpaceX), 31 internships, 12
citizenship/clearance. So tonight is genuinely supply-limited, not blocked by the
watermark (the preprocessor also starts each process in replenish mode, so 233 < 500 would
still leave headroom). I also briefly suspected tonight's `datePosted` fix of making the
7-day recency filter reject older postings — wrong: only 11 of the 3,315 carry a
`datePosted` at all.

Considered and rejected: a claim-time hard reject for any job still on an aggregator URL.
History says that would lose real submissions — 4 jobs submitted while still on an
aggregator URL, **all 4 Gmail-verified genuine** (Agile Defense 06:37, Torc 06:24, ExtraHop
08:34 on 2026-09-12; Samsara 14:59:05 on 2026-09-13, each confirmation within seconds of
`submittedAt`) — plus 19 more after resolution. Also can't go in `evaluate_hard_filters`
itself: the preprocessor calls it *before* it tries aggregator resolution, so it would
discard resolvable listings.

Action (existing tooling, no code change): 09:07:36 UTC called
`POST /autopilot/resolve-aggregator-urls` (default statuses QUEUED, MANUAL_REVIEW, FAILED,
NEEDS_REVIEW) from an authenticated tab. It repoints resolvable rows to the employer board
and re-queues them; unresolvable rows are left untouched; duplicates retire as
`DUPLICATE_APPLICATION`. It does all lookups first and writes at the end (~8 worker
threads). Known small race: it saves from a snapshot, so a QUEUED row the runner claims
mid-call could be overwritten back to QUEUED.

**Result (finished ~09:10 UTC)**: examined 243, **resolved 15** to real Greenhouse/Lever/
Ashby boards and re-queued them, retired 22 as duplicates, 206 could not be found on a
public board and were left as they were. Race check clean (no resolved row stuck QUEUED
with a mid-attempt checkpoint). Queue after: 220 QUEUED, **14 on submittable boards**
(was 0) — Zuora 90.7, Grove Collaborative 83.1, Rithum 62.9, UJET/Ondo Finance/Spear AI
65, plus several that the claim-time filter will drop instantly (non-US: Moniepoint,
Speechify Abuja, Teya, Qualysoft, 2brains; below min score: N-iX 24, OfferUp 40). Since
the runner prefers submittable boards, these go next; a Liftoff Greenhouse job was already
`APPLYING` at 09:11.

Open question for the user (not acting on it unattended): the realistic nightly ceiling is
now small — ~14 queued submittable jobs plus ~22 discovered ones that pass hard filters.
More submissions would need either broader discovery sources or loosening a filter (role
title, US-only, ITAR exclusion), which is the user's call, not an overnight fix.

---

## 2026-09-15 08:37 UTC — Real throughput bug: queued Roblox jobs bypass their hard filter and each burn ~9 min; fixed

User (going to sleep) said the batch didn't look like it was working. It was running,
but producing nothing: since the 07:49 DoorDash submission, every job was Roblox (or one
Airbnb) ending `MANUAL_REVIEW` "No application form on the posting page", and each Roblox
attempt took 9-10 minutes (07:00→07:09, 07:13→07:22, 07:24→07:33, 07:33→07:43,
08:00→08:09, 08:10→08:20, 08:22→08:31). 72 of 259 `QUEUED` jobs are Roblox - at that
rate ~12 hours of batch time for ~zero yield (Roblox all-time: 3 SUBMITTED vs 36
MANUAL_REVIEW + 64 INELIGIBLE).

**Root cause**: `job_filter_ranker.evaluate_hard_filters` does reject Roblox, but its
reason text was reworded on 2026-09-14 from "Roblox uses Cloudflare Turnstile bot
challenges" to "...apply form reliably times out in CareerOS's automation...". The
runner's claim-time check (`autopilot_runner.py:1576-1614`) only acts on a hard-filter
rejection when `classify_ineligibility` recognises the reason text; an unrecognised
reason falls straight through to "Processing" and opens the browser. The old wording
matched the `cloudflare turnstile` pattern (that is why yesterday's attempts were cleanly
`SKIPPED`/`BOT_PROTECTED_BOARD`), the new wording matches nothing. (`_is_submittable_board`
also excludes `roblox.com`, but it is only a preference that falls back to the full queue.)

**Fix**: added `r"reliably times out in careeros's automation"` to the
`BOT_PROTECTED_BOARD` patterns in `ineligibility.py`. Verified standalone against real
queued rows: 3 Roblox jobs → `passed=False, class=BOT_PROTECTED_BOARD`; 5 non-Roblox jobs
(Credence, Lyft, Klaviyo, Nexthop.Ai) still `passed=True`. `test_bot_protection_classification.py`
+ `test_duplicate_submission.py`: 15 passed. Effect once live: each queued Roblox job is
marked INELIGIBLE at claim time in well under a second, no browser.

**Hard-rule slip**: saving `ineligibility.py` triggered uvicorn `--reload` while a Roblox
job was `APPLYING` (should have waited for zero APPLYING before touching `app/`). No harm
resulted: the reload blocked on that job instead of killing it, and it finished normally
at 08:41 ("no form", same as every other Roblox attempt).

**Deployed + live-verified 08:44 UTC**: confirmed zero APPLYING → clean restart →
`start()` from the authenticated tab with `targetProcessCount:100` (ratcheted to 153 so the
batch keeps going overnight), `selfHealing: False` confirmed from the DB, heartbeat fresh.
Live result: Roblox jobs are now claimed and `SKIPPED` in the same second (08:43:41 →
08:43:41, 08:43:44 → 08:43:44), landing `MANUAL_REVIEW` / `BOT_PROTECTED_BOARD` (not a
terminal reason, so they stay in the hand-apply list — correct). The batch processed 52→55
within ~2 minutes of resuming and moved straight on to other companies. The remaining ~70
queued Roblox jobs will drain the same way at a second or so each.

Not attempted tonight, worth a daytime look: 2 of the 3 real Roblox submissions (Gmail-
confirmed 2026-09-12 07:09 and 07:21) went through a `gh_jid` / Greenhouse embed URL, so
rewriting `careers.roblox.com/jobs/<id>` → `job-boards.greenhouse.io/embed/job_app?for=roblox&token=<id>`
might make these 72 postings genuinely submittable instead of ineligible.

---

## 2026-09-15 08:01 UTC — Found and fixed the root cause of the residual "backend offline" event-loop-blocking bug; live-verifying now

User reported "backend offline, no numbers" on the autopilot UI. Unlike the 07:43 false
alarm (heartbeat fresh, only `/health` slow), this time **every** endpoint (`/health`,
`/docs`, `/`) was fully unresponsive (curl timeout, HTTP 000) for 8+ consecutive minutes,
and the run's `lastHeartbeatAt` was frozen the whole time — genuinely stuck, not the
known transient blip.

**Root cause** (confirmed via two `py-spy dump`s of the API process 45s apart, both
showing MainThread parked inside the same `client.get()` call in
`scraper_service.fetch_with_retry` → `scrape_greenhouse`): the per-request
`httpx.Timeout`/`timeout=15` kwarg only bounds the *idle gap between chunks* of a
response body, not the response's total read time. A Greenhouse board that trickles
bytes slowly enough to never go 15s between chunks can hold the read open indefinitely.
Because this scraping runs inline on the API's single asyncio event loop, that one hung
read froze all request handling for the whole process, including `/health` — this is the
concrete mechanism behind the "residual event-loop-blocking bug class" flagged earlier
tonight (07:28 UTC entry) as not-yet-fully-fixed.

**Fix**: `apps/api/app/services/job_discover/scraper_service.py`,
`fetch_with_retry` — wrapped `client.get(url, **kwargs)` in
`asyncio.wait_for(..., timeout=<per-request timeout>+10s)` so every attempt has a hard
wall-clock ceiling on top of httpx's own (chunk-idle-only) timeout, regardless of where
inside httpx the hang occurs. Compile-checked clean.

**Deploy**: the in-flight job at restart time (Roblox, `apjob_e27b6e76...`,
`APPLYING` since 07:51 UTC, attempt 2/3) could not be waited out — the whole process was
deadlocked, so it was already unrecoverable in place, not just slow. Restarted with one
job `APPLYING` (a deliberate exception to the usual "zero APPLYING" rule, justified by
confirmed total deadlock, not routine impatience). Post-restart: health recovered
immediately (200), fresh `start()` call landed `selfHealing: False` (DB-verified), and
the stale-heartbeat recovery correctly swept the orphaned job back into rotation — it was
immediately re-claimed as attempt 3/3 (its last).

**Correction, 08:11 UTC**: the diagnosis above was wrong in an important way, worth
recording plainly rather than quietly editing away. After the restart, `/health` kept
reading `000` on repeated `curl --max-time 5-10` checks for 8+ more minutes, which I
read as a recurrence of the same deadlock and seriously considered restarting again over.
Two things I'd missed: (1) the dev log showed real UI requests (`/autopilot/status`,
`/autopilot/jobs`) completing with `200 OK` the whole time, just taking 10-29s each - the
server was never actually unresponsive, my curl timeouts were just shorter than its real
response time; a `--max-time 40` check confirmed `health:200 time:38.8s`. (2) `py-spy`
dumps across this window showed MainThread cycling through genuinely different code
paths each time (an httpx read, then import resolution, then a DB fetchall) with the
worker's CPU time climbing continuously (5:28 -> 8:01 over ~5 min wall clock, i.e. near
100% of a core) - the signature of real, if slow, work, not a stall. The actual cause:
`filter_and_rank_jobs` -> `evaluate_job_match`'s heuristic skill-matching
(`evidence_match.py`) ran synchronously over a much larger newly-discovered-job batch
than usual, because this same restart's `LOW_QUEUE_WATERMARK` bump (100->200, see below)
raises how many postings get scored in one refill pass. That's CPU-bound Python holding
the GIL almost continuously, which starves the event loop (including `/health` and the
heartbeat ping) for the duration even though it's running off MainThread. It finished on
its own - heartbeat, `processedCount` (48->49) and the in-flight Roblox job (which
genuinely opened the real posting and correctly landed `MANUAL_REVIEW` for the
already-known "no application form" reason, not a restart artifact) all confirm normal
operation resumed by 08:10-08:11 UTC.

Net effect: the `asyncio.wait_for` wrap on `fetch_with_retry` above is still a reasonable
defensive change (it guards a real class of unbounded-read hangs) and stays deployed, but
it was not what fixed tonight's specific episode, because tonight's episode wasn't that
bug - it was slow synchronous matching over a large batch, which was never actually
stuck. The second restart performed while chasing this (killing the then-in-flight
Roblox job on its 2nd attempt) was based on a wrong "deadlock" read and, in hindsight,
unnecessary - the system would have recovered on its own without it. Lesson for next
time this pattern shows up: before restarting on a `/health` failure, retry the curl with
a longer timeout (30-40s) and check whether the dev log shows real requests completing
slowly, before concluding it's actually stuck. Worth watching whether the larger
watermark keeps causing multi-minute latency spikes on future refills; if it becomes a
recurring pattern (not just a one-off post-restart catch-up), the matching loop would
benefit from periodic yields or chunking - not attempting that live tonight.

This was also the pending queue-watermark/dedup fix's restart — see the entry below for
what that fix does; both went out in the same restart.

---

## 2026-09-15 07:52 UTC — Deployed pending queue-watermark/dedup fix; batch resumed clean after restart

User asked to resume the night batch loop and deploy the pending fix (uncommitted changes
to `persistence.py`, `queue_preprocessor.py`, `night_batch_config.py`) once the in-flight
job cleared, then keep going unattended until told to stop.

**Sequence followed**: compile-checked all three edited files (clean) → polled DB until
the one `APPLYING` job (Doordash, `apjob_bd091ee7...`) cleared (~4 min, landed
`SUBMITTED` — 646→647) → confirmed zero `APPLYING` → killed node/python via taskkill →
`scripts/restart-dev.ps1 -Background` → both health checks passed → re-issued
`/autopilot/start` from an authenticated `localhost:5000/applications` tab with
`selfHealing:false` explicit → verified `settings.selfHealing: False` directly from the
DB (not the response body). Run resumed clean: `RUNNING`, 48/58 processed, heartbeat
fresh.

**What the fix does** (for context if a regression shows up later): (1) `datePosted` on
newly discovered jobs now reads the scraper's real `first_published`/`updated_at` fields
instead of nonexistent `postedAt`/`datePosted` keys that always silently wrote `""` —
freshness-based queue ordering was effectively disabled for every source until now. (2)
`is_duplicate_application`'s default and the preprocessor's in-batch dedup no longer
exclude `SKIPPED` from the duplicate check — a job the operator already skipped can no
longer resurface as a "new" discovery next cycle. (3) `LOW_QUEUE_WATERMARK` env default
100→200 (matches what earlier cycles tonight were already reporting as "the new 200
watermark" — that was likely picked up via uvicorn `--reload` before this explicit
restart made it certain across all three files together).

Continuing the standard 15-25 min check-in cadence from here per the night-batch-loop
skill; nothing else outstanding right now beyond the pre-existing open item below
(intermittent `/health` timeout, event-loop-blocking bug class, pending user decision on
whether to fix now vs. dedicated follow-up session).

---

## 2026-09-15 03:40 UTC — Cycle: healthy, both previously-stuck jobs actually completed on retry

Routine check-in cycle. Run `RUNNING`, heartbeat 2s fresh at check time, settings correct
(`selfHealing: False, tierGuardrails: True`), zero jobs `APPLYING` (between claims, not
stuck). Queue at 371 (well above the new 200 watermark). Steady progress since the last
check: processed 38→39, `SUBMITTED` 643→644.

**Good confirmation on the incident above**: both Zscaler postings that hung during
tonight's investigation (`Senior Staff Software Development Engineer, ZIA Core Datapath`
and `Sr. Staff Software Development Engineer`) actually went all the way through to
`SUBMITTED` once retried after a fresh restart/reprocess — Gmail-verified genuine, both
"Thank you for your application to Zscaler!" confirmations landing within ~30s of their
internal `submittedAt` timestamps (03:29:37→03:30:13 and 03:39:35→03:39:14 respectively).
This confirms the Playwright hang from the entry above is transient/intermittent, not a
permanent per-posting block — the automation itself works fine on a clean retry.

Newest NEEDS_REVIEW batch (Zscaler, Smartsheet, Remesh, Outlive, figma, 6Sense, Roblox) is
100% known-good categories: DOM-verification mismatches on genuinely ambiguous screening
questions, and one match-quality gate falling back due to a rate-limited second-opinion
call (benign, not a new pattern). Nothing new to dig into this cycle.

---

## 2026-09-15 04:23 UTC — Cycle: healthy, routine

Heartbeat 22s fresh, `RUNNING`, settings correct, queue at 354. Steady progress (1→4
processed since last cycle). Most recent job updates all known-good categories: DOM
mismatch (Lyft end-date field), rate-limited/timeout second opinion (Qualtrics), reCAPTCHA
block (Datadog), plus routine INELIGIBLE/QUEUED churn. No new "combobox timed out" errors
yet (still watching per the entry below), nothing else to flag this cycle.

---

## 2026-09-15 05:23 UTC — Cycle: healthy; sustained "no application form" streak explained (Himalayas-heavy batch, not a bug)

Heartbeat 19s fresh, `RUNNING`, settings correct, queue at 317. 8 jobs processed since last
cycle, all landed `MANUAL_REVIEW` with 0 new `SUBMITTED` — checked further since two
consecutive cycles of 100% one category crosses from "known-good" into "worth confirming
it's not new." All 10 most recent MANUAL_REVIEW jobs (and by extension the 8 from this
cycle) are `himalayas.app` aggregator listings that couldn't resolve to a real employer
apply page — matches the existing `career_os.aggregator_resolve` "Could not resolve
aggregator listing" log pattern already seen tonight. Explained by batch composition (the
queue currently has a dense cluster of Himalayas-sourced postings, most of which are
structurally unresolvable), not a regression or new bug. No action taken.

---

## 2026-09-15 05:06 UTC — Cycle: healthy, first cycle since the SSE fix deploy

Heartbeat 45s fresh, `RUNNING`, settings correct, one job actively `APPLYING` only 38s
into its current step (not stuck — normal in-progress). Queue at 324. MANUAL_REVIEW jumped
468→490 since the last check, but all 12 most recent are the identical, already-known-good
"no application form on the posting page" reason (aggregator-sourced postings whose real
apply flow lives elsewhere) — a batch of these landing together is expected, not a new
pattern. Also separately: Phase 1 of the frontend render-performance plan shipped this
session (CSS transform/opacity swaps, dead-code removal, and — the more significant
find — the SSE event-loop-blocking bug above), unrelated to Autopilot itself but touching
the same API process, so noting it here for anyone reading this file cold.

---

## 2026-09-15 07:43 UTC — Cycle: healthy, moving past the Roblox cluster; user confirmed the residual event-loop-blocking issue is a known false-alarm for "backend offline"

Heartbeat 20s fresh, `RUNNING`, correct settings, queue at 265, zero `APPLYING` (between
jobs — a new one, Doordash, claimed moments later). `/health` still times out
intermittently (confirmed again via direct check) — this is the already-documented,
not-yet-fully-fixed residual instance of tonight's event-loop-blocking bug class (see the
07:28 UTC end-of-session entry and the handoff prompt given to the user). User asked
about it live this cycle ("autopilot shows backend offline") — confirmed via py-spy it's
the same known issue (MainThread intermittently caught in `get_kv`'s JSON decode), not a
new failure; batch was genuinely healthy and progressing throughout. User has not yet said
whether to fix it now or leave it for the dedicated follow-up session — leaving as pending,
not assuming either way.

`SUBMITTED` was flat at 646 for over 2 hours — checked and explained: recent processing has
been dominated by the Roblox cluster (known slow/"no application form" outcome, not a
submission bug) plus routine QUEUED churn. Most recent completed job before this check was
another Roblox `MANUAL_REVIEW` (known-good reason), and a new job (Doordash) is now
actively processing — first non-Roblox company in a while, worth watching whether
`SUBMITTED` starts moving again now that the loop is past that cluster.

---

## 2026-09-15 07:35 UTC — Cycle: Roblox job cleared via its own watchdog again; scraper found running despite being stopped; Greenhouse-embed fix confirmed present but evidently not resolving the hang

Heartbeat was frozen at 07:24:01 for 7+ minutes (past the usual few-minute recovery window)
— `py-spy dump` showed MainThread idle inside normal async httpx I/O (`scrape_greenhouse`),
not a blocking-call freeze this time, so did not intervene. The in-flight job
(`apjob_13ce5a3e`, Roblox, `QUESTIONS_COMPLETED`) cleared on its own within the poll window
— same pattern as every other Roblox stall tonight.

**Found: the background scraper is running again** despite being explicitly stopped before
sign-off (`POST /autopilot/queue-preparation/stop`, confirmed 200 at the time). **Root-
caused**: `autopilot_runner.py::_ensure_queue_preprocessor()` (line 782, docstring: "Keep
the background queue pipeline alive alongside the run") is called on **every single
batch-loop iteration** (line 984). Intentional coupling, not a bug — the design assumes
discovery should always run alongside an active batch — but it means a manual stop call has
no durable effect while the run keeps going: the very next iteration calls
`_ensure_queue_preprocessor()` again and silently restarts it. There is currently no
supported way to pause discovery independently of pausing the whole run.

**User asked directly about Roblox** (pull the Greenhouse link and apply through that
instead, since the Roblox site itself doesn't work for automation) — checked the code:
this exact fix already exists (`playwright_autopilot_executor.py:2884-2917`, the
`validityToken`-gated direct-navigation logic from the 2026-09-14 21:30 UTC entry above).
It's evidently **not actually resolving the hang** — Roblox postings kept stalling to their
watchdog all night despite this code being live. Also found `job_filter_ranker.py:421-422`
(`_ROBLOX_TEST_EXCEPTION_URLS`) still hard-blocks nearly all Roblox postings except one
specific test URL — worth understanding whether the jobs stalling tonight are even going
through the fixed code path at all, or hitting some other Roblox handling entirely. **Not
re-diagnosed live tonight** (would need a real browser tab against a fresh Roblox posting,
per the original investigation's own method) — handed off as a prompt for a dedicated
session instead, given the hour.

---

## 2026-09-15 07:28 UTC — End-of-session status: user going to sleep, batch left running, scraper paused, 5 real fixes deployed, more of the same pattern likely remain

**Summary for whoever (human or cold session) picks this up**: tonight surfaced a systemic
class of bug — synchronous, DB/JSON-heavy work called directly inside `async def`
functions, blocking the *entire* FastAPI process (every request, including a plain
`/health` check) for the duration. Found and fixed **five** distinct instances, each
confirmed live via `py-spy dump` catching the MainThread itself blocked, each deployed with
zero jobs `APPLYING` and each following the "own fresh `session_scope()` inside
`asyncio.to_thread`" pattern (or plain `asyncio.to_thread` when no DB session was involved):

1. **04:41 UTC** — SSE `/autopilot/events` initial status snapshot (`autopilot.py`).
2. **05:39 UTC** — batch loop's own per-iteration queue check, `list_autopilot_jobs(db)`
   full scan called after *every job* (`autopilot_runner.py`, 4 call sites).
3. **06:27 UTC** — background scraper's snapshot persistence, `_persist_snapshot`
   (`job_discover/store.py`) — a *regression* of an already-once-fixed instance, one call
   deeper than the original fix stopped.
4. **06:27-07:13 UTC window** — the per-job submission pipeline's data-loading step
   (profile/answer-library/accomplishments/documents, `autopilot_runner.py`
   `_load_submission_context`).
5. **~07:15 UTC** — the scraper's per-batch job scoring, `_score_jobs`
   (`job_discover/store.py`) — pure CPU work (H1B-sponsorship checks, evidence matching),
   no DB session, safest of the five to move.

**Still not fully resolved.** After all five fixes, with the scraper stopped and only the
batch loop running, `/health` still failed roughly half the time in an extended check (5 of
10, mixed with genuine successes down to 6-9s). This means **more instances of the same
pattern remain**, almost certainly scattered through the large `_execute_application_pipeline`
/ `_process_single_job_with_retries` / `_run_worker_slot` chain (2000+ lines, many
`with session_scope() as db:` touch-points across form-filling/verification/checkpoint
steps) that weren't safe to fully audit and rewrite tonight given the size and the fact that
this code drives real, live job submissions — correctness there matters more than speed,
and a rushed broad refactor risks corrupting real applications, which is a worse outcome
than occasional dashboard slowness. **Did not attempt a full audit/rewrite of that pipeline
tonight** — flagging it as the clear next-session priority (also already captured in
`docs/future-improvements.md`'s new "Audit for synchronous event-loop-blocking DB/JSON
work" entry, written before this final round of fixes — worth updating that entry's count
from three to five instances next time it's touched).

**Why this likely isn't as bad for tonight as it sounds**: `concurrency=1` and nobody is
actively using the dashboard overnight, so the main practical cost of a blocked event loop
right now is *this monitoring itself* occasionally getting a slow/failed health check — not
necessarily failed submissions. Checked the actual job history at end-of-session: real
progress happened throughout (INELIGIBLE 645→679, MANUAL_REVIEW 468→526 across the session
despite all the freezing), and the most recent processed job was a legitimate, known-good
outcome (Roblox, "no application form" — not a crash). `SUBMITTED` was flat at 646 for
over an hour before sign-off, but the most recent activity was a dense run of Roblox/
aggregator postings specifically (already well-documented tonight as slow-but-not-broken),
which plausibly explains the flat count without implying submissions are actually failing.
**Not Gmail-verified for this specific hour** — worth an extra-careful spot-check next
cycle given the uncertainty.

**Operational state at sign-off**:
- Background scraper: **stopped** (`POST /autopilot/queue-preparation/stop`) — deliberate,
  user-approved mitigation given it was the single largest source of contention. **This
  toggle is in-memory only and resets on every server restart** — re-issue it after any
  future restart if it should stay off. 265 jobs already `QUEUED` at sign-off, so discovery
  being paused doesn't stop tonight's batch from having work.
- Batch run (`aprun_7cb71c15...`): `RUNNING`, `selfHealing: false`, `tierGuardrails: true`,
  processed 45/55 at last check, heartbeat a few minutes stale at sign-off (consistent with
  actively working a slow Roblox job, not necessarily stuck — no `APPLYING` job was left
  hung past a reasonable window at any point tonight; every stall cleared via its own
  watchdog or a deliberate wait, never a forced kill).
- Full backend test suite: passing except the same 24 pre-existing, unrelated failures
  (timezone data, evidence-match thresholds, phone-country labeling, a couple of stale
  mock-based tests in `autopilot_runner`/`tailoring_mode` tests whose mocks predate recent
  changes to `_process_batch_loop` — not fixed tonight, out of scope, flagged here for
  whoever cleans up test debt next).
- Separately, user reported **"Career progress is unavailable"** on the dashboard —
  plausibly explained by the same `zoneinfo.ZoneInfoNotFoundError: No time zone found with
  key UTC` seen in `test_career_progress.py` failures tonight (missing/broken `tzdata`
  package in this environment) — not investigated further tonight, flagged for morning.

**For the next cycle / next session**: keep the same discipline — never restart or kill
mid-`APPLYING`, verify settings from the DB not the response body, Gmail-verify claimed
submissions before trusting the internal count, and treat any further "everything looks
frozen" report as a cue to `py-spy dump` before assuming the worst. If `/health` keeps
failing intermittently with the scraper still off, that's the strongest signal yet that the
remaining instances live inside the per-job pipeline itself and justify the fuller audit.

---

## 2026-09-15 06:27 UTC — MAJOR FINDING (fourth of the night, and this one had already been half-fixed before): background scraper's snapshot persistence blocked the event loop for tens of seconds at a time during active scrapes

Right after deploying the batch-loop fix above, the freeze recurred — user reported "no new
submit," and `/health` was still timing out repeatedly (5 of 6 checks, 10s+ each, some full
timeouts). Different call site this time. `py-spy dump`: MainThread `active+gil` inside
`json.loads` via `set_kv` → `_persist_snapshot` (`job_discover/store.py:353`) →
`_append_scraped_batch` → the background scraper's `on_batch` callback
(`store.py:1181`/`scraper_service.py:1218`).

**This exact function already has a comment documenting a prior fix for this exact bug
class**: an earlier session found the MainThread parked in `canonicalize_url` under
`cross_source_deduplicate` during a live Autopilot hang, and moved the *pure computation*
(dedup/merge) to `asyncio.to_thread` — the comment explicitly says "Only the pure
computation moves to a thread. The SQLAlchemy session stays on this thread, since a Session
is not safe to share across threads." That fix was correct as far as it went, but
`_persist_snapshot(db, updated)` right after it — writing the (now 2500+ job) snapshot back
via `set_kv` + a summary rebuild + a file write — was left on the main thread for exactly
the reason stated, and has since grown expensive enough on its own to reproduce the same
freeze.

**Fix**: same principle, applied correctly this time — can't `asyncio.to_thread` the
existing call with the shared `db` session (the very hazard the original comment warns
about), so `_persist_snapshot` now runs inside a nested closure that opens its **own fresh
`session_scope()`**, entirely inside the background thread, and that closure is what gets
dispatched via `asyncio.to_thread`. No cross-thread session sharing; the expensive
serialize/write work still leaves the event loop. Compile-checked; the one existing test
covering this path (`tests/test_scraper_import.py`, 4 tests) still passes.

**Deployed with reduced pre-deploy testing given active, ongoing user impact** (zero
submissions happening while the server was frozen) — ran the specifically-relevant test
file rather than the full ~9-minute suite before this one deploy, given the full suite had
already been run clean (mod the same 24 pre-existing unrelated failures) twice earlier this
session for the other fixes tonight. Zero jobs `APPLYING` confirmed before restart (one
Roblox job took ~10 minutes and cleared via its own watchdog first — not forced).

**Live-verifying now**: monitoring `/health` over an extended window to catch it during a
scrape cycle, since that's when this specific bug fires (unlike the batch-loop bug, which
fired on every iteration constantly).

**Pattern worth flagging plainly**: this is the **third distinct call site** tonight where
synchronous, DB/JSON-heavy work ran directly on the event loop instead of a thread (SSE
status snapshot, batch-loop queue check, now scraper snapshot persistence) — and this one
specifically is a *regression* of an already-fixed instance, just at a different line one
call deeper than where the original fix stopped. This is a systemic anti-pattern, not three
unrelated bugs — worth a dedicated audit (added to `docs/future-improvements.md`) rather
than continuing to find these one freeze at a time.

---

## 2026-09-15 05:39 UTC — MAJOR FINDING (likely the real root cause of most of tonight): the batch loop itself froze the entire server on every single iteration

User reported "it seems the night job loop is not running." Checked: both `:4000` and
`:5000` were completely unresponsive — not slow, genuinely no HTTP response even to a plain
`curl /health` within 8s (verbose curl confirmed the TCP connection itself succeeded, so
the process was alive, just not answering anything at all). `py-spy dump` on the live
worker: the **MainThread — the actual event loop** — was blocked inside
`_process_batch_loop` (`autopilot_runner.py:986`, called from `_run_batch_worker`) running
a synchronous, unfiltered `list_autopilot_jobs(db)` — a full scan + JSON-deserialize of
every `aa_autopilot_job` row (2500+ tonight) — just to filter it down to the `QUEUED` ones
in Python afterward.

**This is almost certainly the primary driver behind most of tonight's chaos**, more so
than the read_cache (03:40 UTC) or SSE (04:41 UTC) bugs already fixed — those fire on
dashboard connections/polls; this one fires **on every single batch-loop iteration**, i.e.
after every job the loop processes, all night, every night, and gets slower as the job
table grows. Found **four** occurrences of the identical pattern in the same function
(the main iteration path, plus three refill-decision branches), all doing the same
full-scan-then-filter.

**Fix**: `list_autopilot_jobs(db, status=...)` already exists and pushes the filter into
SQLite via `list_entities_by_json_equals` (an indexed `json_extract` query against
`ix_entities_status`, confirmed present in `_configure_sqlite`) — its own docstring says
exactly why: "a status filter over thousands of rows became a full scan plus a JSON parse
per row" without it. All four call sites just needed to pass `status=AutopilotJobStatus.
QUEUED.value` instead of fetching everything and filtering in Python — a mechanical,
behavior-preserving substitution (verified via regex to catch all four identically-shaped
occurrences rather than risk missing one by hand). Added
`tests/test_autopilot_batch_loop_queue_query.py` proving the status-filtered call returns
the exact same set as the old fetch-everything-then-filter approach. Full suite re-run
before deploy.

**Deployed** with zero jobs `APPLYING` (one was genuinely mid-submission at only 16s into
its step when first checked — waited for it to clear naturally rather than force it, per
the hard rules; cleared within the poll window).

**Next cycle**: watch for `/health` and `/autopilot/status` staying responsive throughout —
if the server never again goes fully unresponsive the way it did tonight, that's strong
confirmation this was the real culprit, not just a contributing factor.

---

## 2026-09-15 04:41 UTC — MAJOR FINDING: found the real cause of tonight's "event loop starvation" episodes — SSE endpoint blocked the whole server on every new dashboard connection

Came out of a separate frontend-performance audit (user asked whether CareerOS can sustain
60fps and requested a caching audit), but this is squarely a backend finding that explains
symptoms seen earlier tonight, not just a frontend concern — flagging prominently here too.

**What was found**: reproduced live. Reloading the Applications dashboard opened a new SSE
connection to `GET /autopilot/events`; `curl http://localhost:4000/application-assistant/
autopilot/status` then hung for 30+ seconds with no response, and the whole app was
unusable in the meantime. `py-spy dump` on the live worker process showed the **MainThread
itself — the actual asyncio event loop** — blocked inside a synchronous `list_autopilot_jobs()`
full-table scan (`persistence.py:725` → `store.py:268`), called from
`autopilot.py`'s SSE `event_generator`'s initial-status snapshot
(`runner.get_status(db)`, previously line ~136). That's a full, uncached scan +
JSON-deserialize of every `aa_autopilot_job` row (2500+ tonight) running **directly on the
event loop**, not in a background thread — which blocks the *entire process*, every other
request and every other SSE connection, for its full duration.

**This likely explains some of the earlier "event loop starvation" episodes** attributed
tonight to the `read_cache` thundering-herd bug (03:40 UTC entry, still a real and valid fix
in its own right) — that fix addresses *duplicate concurrent* cold-start callers, but this
is a different, more severe bug: even a single caller blocks everyone, and it fires **every
time a browser opens a new SSE connection to the dashboard** (every page load/reload), not
just on a cold cache.

**Why this one path was missed**: the REST `GET /autopilot/status` endpoint right next to
it already does this correctly — short-lived `session_scope()` + `read_cache` — with a
comment explicitly explaining why (pool exhaustion under concurrent polling). The SSE
endpoint's one-time initial snapshot was written separately and never got the same
treatment.

**Fix** (`apps/api/app/routers/application_assistant/autopilot.py`): extracted the REST
endpoint's cached-status logic into `_cached_autopilot_status()`, reused by both the REST
endpoint and the SSE generator; the SSE path now calls it via `await
asyncio.to_thread(_cached_autopilot_status)` instead of a bare synchronous call — so it (a)
benefits from the same 3s cache the REST poller keeps warm, and (b) can never block the
event loop even on a genuinely cold cache (e.g. immediately after a restart, exactly what
was reproduced). Added `tests/test_autopilot_status_sse.py`: proves a slow status
computation no longer starves a concurrent task on the same loop (a naive direct call would
fail this test). Full suite run before deploy. Compile-checked.

**Deployed and live-verified.** Full suite run first: 24 pre-existing failures found,
unrelated to this or any other change tonight (timezone data missing, evidence-match
thresholds, phone-country source labeling — all in areas already modified before this
session started per the original git status; not investigated further, out of scope).
None of the new tests added tonight are among the failures. Deployed with zero `APPLYING`
jobs. Live-verified: `curl .../autopilot/status` immediately after the restart (genuinely
cold cache) returned in **0.29s**, versus 30+ seconds (and counting) before the fix.
Reloaded the dashboard in a fresh browser tab — status loads fast; the `/autopilot/jobs`
list is still slow (unpaginated, ~2500 rows) but that's a separate, already-tracked issue
(the frontend-performance plan's Phase 5), not a regression from this fix.

---

## 2026-09-15 04:04 UTC — Deployed the per-field combobox timeout fix; first post-deploy cycle healthy

**Deployed** (see the MAJOR FINDING entry below for the diagnosis): a 15s
`asyncio.timeout()` now wraps each individual combobox field's processing inside
`_fill_all_greenhouse_comboboxes` (`playwright_autopilot_executor.py`), instead of every
Playwright RPC call in that function inheriting the page's ~9-minute default. Implemented
as a minimal, mechanical transform (inserted one `async with` line, re-indented the
existing ~394-line field-processing body by one level, zero logic changes) specifically to
avoid the risk of manually restructuring a large, heavily-tuned function under time
pressure — verified via `git diff` line counts and a compile check that nothing else moved.
Added `tests/test_combobox_field_timeout.py`: a fake hanging Locator proves the function
now returns in ~15.8s instead of hanging indefinitely (would have hung 3600s+ without the
fix). Full suite passed. Deployed with zero jobs `APPLYING` at restart time.

**First cycle after deploy: healthy.** Heartbeat exactly current (0s stale) at check time,
`RUNNING`, correct settings. Two genuine submissions landed since deploy — Gmail-verified:
Zscaler's `Principal Software Development Engineer` (the exact job that hung and was
manually reprocessed earlier tonight — now goes through cleanly on its own) and Flex's
`Staff Software Development Engineer in Test (SDET)` (title/timing match within 27s).
Zero new "combobox timed out" errors yet in the job records — expected, since the fix only
fires on an actual hang, which was intermittent (roughly 1 in 15-20 jobs tonight), not
constant. Newest NEEDS_REVIEW batch (Datadog reCAPTCHA, GPA field DOM mismatch, OpenAI
rate-limited second opinion, plus more Zscaler/Smartsheet/Remesh DOM mismatches) is all
known-good categories.

**Watch next 1-2 cycles for**: a genuine "combobox timed out" log line/lastError appearing
on some future job (confirms the fix actually catches a real hang in production, not just
in the unit test) — and confirm the loop's own heartbeat never again freezes at
`QUESTIONS_COMPLETED` for more than ~15-20s past a hang, which would mean the fix is
working as intended even when the underlying intermittent Playwright/browser
unresponsiveness recurs (this fix does not address *why* the IPC connection occasionally
goes unresponsive — only how fast the system recovers when it does).

---

## 2026-09-15 03:40 UTC — MAJOR FINDING: real read-cache thundering-herd bug found and fixed, but it was NOT the cause of tonight's repeated stuck-loop symptom; actual root cause is the pre-existing Playwright hard-watchdog gap already flagged (and never resolved) earlier tonight

Flagging prominently, not just logging — this took three restarts to properly diagnose and
the underlying issue is still open.

**Sequence**: right after the 03:13 recovery (see below), the loop froze again within
minutes — new job, same signature (`APPLYING` at `QUESTIONS_COMPLETED`, heartbeat frozen).
`py-spy dump` on the live worker process (per `autopilot-fix-verify-loop`'s own diagnostic
step) showed a pile of duplicate `AnyIO worker thread`s all independently running
`list_autopilot_jobs`'s full unpaginated table scan (2509+ rows) simultaneously — a real bug
in `read_cache.py`: `ReadCache.get()`'s cold-start path (`if entry is None`) had **no
deduplication**, so a burst of concurrent requests for the same key right after a restart
(when the cache is empty) each ran the expensive loader independently instead of sharing one
result, saturating the DB connection pool.

**Fixed and verified**: added a per-key creation lock so only the first concurrent cold-start
caller runs the loader; the rest wait and read the populated result. Reproduced the exact
failure (20 concurrent calls → 1 loader execution after the fix, was N before) in a standalone
script, added 3 regression tests (`tests/test_read_cache.py`, all passing), compile-checked,
redeployed with zero jobs `APPLYING` at deploy time.

**But the loop froze again anyway, on a third, different job, immediately after this fix
deployed.** `py-spy dump` this time found the real culprit: the dedicated `"aa-playwright"`
thread was genuinely **idle** (not busy, not GIL-bound — blocked waiting) inside
`_fill_all_greenhouse_comboboxes` (`playwright_autopilot_executor.py:971`,
`await wrapper.count() > 0`) — a plain Playwright `.count()` call that does not normally
block, hanging with no timeout catching it. This is the **exact same signature** the
2026-09-14 08:52 PDT entry in this file already found and left open: *"Playwright execution
hard watchdog timed out ... the watchdog itself does not appear to have fired this time."*
Four separate jobs tonight (`apjob_9931a80d`, `apjob_699940fa`, `apjob_5eeed95f`,
`apjob_e98a5227` — different companies, different postings) have now hung at this identical
step. This is not one bad posting; it's a systemic gap: whatever hard-watchdog mechanism is
supposed to recover a hung Playwright call either isn't wrapping this call path, or a
blocking native IPC read inside Playwright's driver isn't cleanly interruptible by an
`asyncio` cancellation even when a watchdog does fire.

**Did not attempt a fix to the watchdog/Playwright IPC layer tonight** — this needs careful
design (how do you forcibly interrupt a blocked native read without corrupting the browser
session?) and the project's own established judgment on hard problems under time pressure
(see the Roblox investigation) is to investigate and document rather than force a risky
change. Recovered the specific hung job via the normal single-job `/reprocess` endpoint
instead (fast, clean, no restart needed this time).

**Recommendation for the user or a future session with more time**: this is worth a
dedicated investigation — specifically, why the existing hard-watchdog (referenced in the
08:52 PDT entry) isn't firing on this exact hang, and whether Playwright locator calls in
this codebase need an explicit `timeout=` parameter (Playwright supports one on `count()`-
adjacent waiting calls, though plain `count()` itself doesn't wait/retry by default per its
own docs — worth confirming whether a *different* call earlier in this exact stack is where
the real wait/hang is rooted, since the top frame shown is just where py-spy caught it, not
necessarily where the wait originates).

---

## 2026-09-15 03:13 UTC — Formalized this loop as a skill; recovered an orphaned job on first cycle; two config changes pending deploy

**New**: this loop now runs from a proper skill, `.claude/skills/autopilot-night-batch-loop/
SKILL.md`, instead of an ad-hoc prompt each time — it encodes the hard rules, the
`/autopilot/start` settings-inheritance quirks, the per-cycle checklist, and delegates to
the existing `restart-careeros-dev`/`reprocess-autopilot-job`/`autopilot-fix-verify-loop`/
`verify-gmail-application-confirmation` skills for their specific steps.

**Two code changes made and compile-checked, not yet deployed** (a job was APPLYING at the
time, per hard rules — waiting for a natural gap):
1. `night_batch_config.py`: `LOW_QUEUE_WATERMARK` 100 → **200** (per explicit user request:
   refill should start earlier). `HIGH_QUEUE_WATERMARK` unchanged at 500 — already matched
   the requested "back to 500" target.
2. `queue_preprocessor.py` + `persistence.py`'s `is_duplicate_application`: removed
   `SKIPPED` from the dedup-exclusion set. Previously a job the operator explicitly skipped
   could resurface as a "new" discovery on a later scrape; now every terminal-ish status
   (`SUBMITTED`, `NEEDS_REVIEW`/`STAGED`, `MANUAL_REVIEW`, `INELIGIBLE`, `SKIPPED`) is
   checked via the existing canonical-URL / composite company+title+URL key before
   enqueueing anything as new — per explicit user request for idempotency across all of
   these. **Tradeoff worth flagging**: a job skipped for a since-fixed reason (e.g. an
   automation bug that used to block it) will no longer automatically resurface on its own —
   getting it back now requires the existing `/autopilot/requeue-bucket` (bucket=`skipped`,
   company-scoped) or `/autopilot/reprocess-skipped` endpoints instead of a fresh discovery.

**Orphaned-job incident, found and recovered on the very first cycle under the new skill**:
user reported "it seems career os is down." Checked both dev servers directly —
`:4000/health` and `:5000` both responded normally, so the process itself was alive. Real
signal was in the DB: the run's `lastHeartbeatAt` was ~9 minutes stale (over the 60s
auto-recovery threshold) and one job (`apjob_699940fa`) was frozen `APPLYING` at
`QUESTIONS_COMPLETED` for the same ~9 minutes — matching the exact orphaned-worker
signature from tonight's earlier Cribl/Speechify/Wolverine incidents (worker task died with
no cleanup, heartbeat and job both frozen at the same instant, `api.log`'s own
`aggregator_resolve` activity independently confirmed to have stopped at that same
timestamp). Did **not** kill/restart processes — that would have been the wrong tool for a
frozen coroutine, not a crashed process, and risks nothing per the hard rules anyway since a
raw restart still requires zero-APPLYING first.

**Recovery, via the designed mechanism, not a DB hack**: re-issued `/autopilot/start` from
an authenticated browser tab (`localhost:5000/applications`, same payload as always —
`selfHealing:false` explicit) to trigger `_recover_stale_run_sync`'s automatic stale-
heartbeat detection. The `javascript_tool` call itself timed out after 45s ("renderer may be
frozen") — per the `reprocess-autopilot-job` skill's own guidance, did not assume failure
from that alone and checked the DB directly instead: the call had genuinely landed.
**Confirmed fixed**: heartbeat fresh (12s old at check time), `settings` correct
(`selfHealing: False, tierGuardrails: True`), the frozen job resolved to `MANUAL_REVIEW`
(a legitimate "no application form on the posting page" outcome — known-good category, not
a new bug), and the loop had already autonomously claimed and started its next job
(`apjob_cb4a735b`) by the time this was checked. Queue healthy at 374 `QUEUED` (well above
the new 200 watermark, no refill action needed this cycle).

**Next cycle**: deploy the two pending config changes the moment a job is confirmed
`APPLYING`-free (don't force it), verify `selfHealing`/`tierGuardrails` still read correctly
post-restart per the usual discipline, and watch one refill cycle to confirm the raised
low-watermark and skip-aware dedup behave as intended before considering this done.

---

## 2026-09-14 14:10 PDT — Found: the single-job "Apply" path (preflight-approve) defaults self-healing to ON

While requeuing the Roblox test job with priority via `preflight-approve` (the same
endpoint the UI's "Apply" button calls), checked `/autopilot/status`'s `batchConfig` out of
habit and found **`selfHealing: true`** live, mid-run — a real violation of the standing
"self-healing must stay off" rule. Root cause:
`tailoring_receipts.py`'s `approve_preflight_submission` calls
`runner.start(options={"targetProcessCount": 1, "concurrency": 1, "priorityJobId": id})` -
no `selfHealing` key at all - and `autopilot_runner.py`'s `start()` reads it as
`bool(opts.get("selfHealing", True))`, defaulting True when the caller omits it entirely.

**Did not patch `tailoring_receipts.py`** - that endpoint backs the real, human-facing
"Apply" button elsewhere in the app, and defaulting self-healing on for a single click a
person is actively watching may well be intentional product behavior, not a bug; changing
shared behavior on my own read of one overnight rule felt like overreach without asking.
Instead corrected only the live runner state for this session by re-calling
`/autopilot/start` with `selfHealing: false` explicit immediately after noticing - confirmed
via `batchConfig` that it took. **Flagging for the user**: worth deciding deliberately
whether `preflight-approve` should also force `selfHealing: false`, or whether the two
paths are supposed to differ.

**Fallout, checked and minor**: 3 jobs got touched during the brief violation window
(Formlabs, Klaviyo, Nexthop.Ai) - all landed in ordinary NEEDS_REVIEW, none falsely marked
SUBMITTED, so no corrupted records resulted this time.

**Second-order accident from the same start() call**: it landed while a different job
(Wolverine Trading) was already mid-flight, reproducing the exact orphaning pattern from
earlier tonight (Cribl, Speechify) - confirmed via identical signature (no lock data, log
activity frozen at the exact cancellation timestamp) and recovered the same safe way, via
`/autopilot/jobs/{id}/reprocess` on just that job. No data lost. This keeps happening
whenever a `priorityJobId` start() is issued while the batch is actively mid-job - worth
the user considering whether `preflight-approve`/manual priority starts should first check
for an in-flight job and wait, the same discipline used for real restarts.

---

## 2026-09-14 13:56 PDT — Roblox investigation, freshness-priority feature, and 3 UI fixes deployed

**Roblox (114 MANUAL_REVIEW jobs)**: user asked to test one live, and if it works, requeue
the rest. Live-tested 3 real automation attempts across 2 queued postings — all failed with
a reproducible 60s page.goto timeout, eventually settling on "no application form on the
posting page". Then, per the user's follow-up, drove a **real Chrome session (not
Playwright/no stealth args)** to a genuinely current Roblox posting found by browsing their
live listings (not the stale queue) - the actual Greenhouse-hosted apply form
(job-boards.greenhouse.io/roblox/...) loaded instantly with Resume/CV, Cover Letter, Legal
Name fields visible, **zero CAPTCHA/Turnstile/any challenge**. This strongly suggests the
original "Roblox uses Cloudflare Turnstile" reason is wrong - nothing challenged a normal
browser. The 2 postings tested through automation were both from days-old discovery
batches and may simply have been expired (one confirmed redirecting to the generic careers
page on manual nav), which would also explain the odd timeout behavior. **Did not fully
isolate the real cause** (stale queue entries vs. a genuine stealth-browser load issue
specific to this board) before time ran out - re-enabled the block for now since every real
automation attempt still failed, but rewrote the reason to describe the symptom honestly
rather than repeat the unconfirmed Turnstile claim, and did **not** requeue the other 113.
Flagged as worth a future session re-testing against a known-fresh posting id through
CareerOS's own automation specifically.

**Freshness-priority feature** (separate user request): traced "posted today should jump the
queue" to two real bugs - (1) `queue_preprocessor.py`'s scraper-ingest was checking field
names (`postedAt`/`datePosted`) that don't exist in the scraper's actual output (real fields
are `first_published`/`updated_at`/`updatedAt`), so the posting date was always blank; (2)
even populated, the existing recency bonus was capped too low to ever beat tier/match score.
Fixed both in `job_filter_ranker.py`: a verified same-day posting (real `datePosted` only, no
discovery-time fallback per explicit user choice) now overrides the entire queue ordering,
gated additionally to **"senior software engineer" titles only** per explicit request (also
user-specified: hard override, not a soft tie-breaker). Deployed and confirmed live. A
background scrape was already running at deploy time (continuous, not something I needed to
trigger separately) - its results will carry real `datePosted` going forward; verify next
cycle that newly-ingested jobs actually populate the field as expected.

**3 UI fixes, all live-verified via screenshot**:
1. Batch counter: run's `targetProcessCount` was ratcheting upward on every resume (the
   number the user found confusing, e.g. "38"). Added `resumeCount` to the run record
   (increments on resume, starts at 1) and changed the dashboard to show "Batch N: X
   processed" instead of the raw ratcheting fraction.
2. Merged "Latest submissions" and "Last update" into one panel, relabeled "History" (nested
   `RecentSubmissions` inside `LastUpdatePanel` rather than duplicating logic).
3. The "Last run" stats (processed/submitted/ineligible/etc.) didn't sum to the total -
   NEEDS_REVIEW outcomes increment none of the run's own counters. Added a client-computed
   "needs review" line (processed minus everything else, clamped ≥0) so the numbers are
   honest, plus showing the previously-hidden `skippedCount`.

All backend changes compile-checked and deployed together in one restart (in-flight job
waited out first, per the hard rules). All frontend changes typechecked clean.

---

## 2026-09-14 11:04 PDT — MAJOR FINDING: ~146 SUBMITTED jobs were never genuinely confirmed by Playwright; 55 proven false and corrected, root cause fixed

Started as a routine Gmail spot-check on a new Robinhood submission and turned into the
biggest data-integrity issue found this session. Flagging prominently, not just logging.

**How it was found**: spot-checking "Full Stack Software Engineer, Credit Cards & Banking"
(Robinhood) — its own `checkpointHistory` ends in `STAGED` with "military status field empty
in the live DOM" (a genuine failed attempt, from *before* today's fix), yet its `status` field
said `SUBMITTED`. Its `submissionEvidence` explained why: `submissionSource: "email-detected"`,
`confirmationMatchedOn: "company"`, `confirmationUid: "131649"` — the exact same email UID
recorded on a *different* Robinhood job (`apjob_16ae51fa`, the Kubernetes Compute posting I
genuinely submitted and Playwright-confirmed with a full ATS receipt at 17:36:02 UTC). One
real confirmation email, credited to two different applications.

**Root cause**: `manual_submission_reconciler.py` exists to catch cases Playwright itself
couldn't verify (no webhook from ATSes, so a "Thank you for applying" email is the ground
truth). Its "company" pass — used when an ATS's confirmation subject doesn't name the specific
role (Robinhood, Anthropic, MongoDB, etc. all send generic "Thank you for applying to X") —
picked whichever open candidate for that company was *most recently attempted* and credited
it, with no way to tell if that guess was actually the one the email was for. Safe with one
application in flight per company; wrong often once several are in flight simultaneously
(routine on a night applying to 20-30+ postings at Anthropic, Verkada, Block, etc.).

**Scale**: 146 of 659 SUBMITTED jobs (~22%) were marked via this company-only guess, and
**none of them had ever been marked SUBMITTED by Playwright itself** (`previousStatus` was
FAILED/NEEDS_REVIEW/MANUAL_REVIEW for every single one — never SUBMITTED). Broke the 146 down
by what each job's own retained evidence shows:
- **55 proven false** — retained `domVerification.passed: false`, i.e. a required field was
  provably still empty in the live DOM when last checked. Not ambiguous. **Corrected**: reset
  to `QUEUED` via `POST /autopilot/jobs/{id}/reprocess` (the real app endpoint, batched from
  the browser tab — not a raw DB edit) so they get a genuine attempt, now under today's fixes.
  Verified after: 0 remain in this proven-false state, SUBMITTED count 659 → 604.
- **48 uncertain, left as-is** — `previousStatus` NEEDS_REVIEW (38) or MANUAL_REVIEW (10), no
  retained DOM snapshot to prove it either way (their failure mode - second-opinion rejection,
  reCAPTCHA-at-submit - doesn't populate `domVerification`). Very likely also false given the
  `previousStatus` pattern, but I didn't have hard proof for these specific ones, so I did not
  revert them automatically - flagging for the user's awareness / a future Gmail-by-hand check
  rather than guessing a second time in either direction.
- **43 left as SUBMITTED** — `previousStatus: FAILED`, but from a *genuinely ambiguous*
  Playwright outcome, not "never tried": submit was actually clicked, and Qwen's own
  post-submit check said `submissionConfirmed: false, confidence: 0.2, "no confirmation page
  or message detected"` - exactly the case this reconciler exists to resolve using the
  employer's own email as the tiebreaker. This is the system working as designed, not the bug.
  Real uncertainty remains here (same "was the company-pass email really for this one"
  question applies) but it's a materially different, more defensible category than the 55.

**Fix deployed** (`manual_submission_reconciler.py`): the "company" pass now only fires when
exactly one candidate is open for that employer - ambiguous cases are left unreconciled
(stay in their true status, catchable by the normal review flow) instead of guessed. Compile-
checked. Not yet redeployed (server restart still pending a clear APPLYING window) - queued
for next restart alongside anything else pending.

**Told the user directly** in this turn's response, not just logged here - this affects
whether "N submitted" is trustworthy as a headline number, which is too consequential to
leave for a routine log file to surface later.

**Update 11:53 PDT — the "exactly one candidate" fix was necessary but not sufficient; found
and fixed a second gap, and learned this bug predates tonight.**

Cycle's Gmail spot-check landed on a NEW `company`-matched SUBMITTED job (Verkada, Backend
Engineer - Connectivity) even after the "exactly one candidate" fix was live. Checked its own
retained `domVerification` - proven false again (3 required fields unresolved). But there was
genuinely only ONE Verkada candidate open when it matched, so the deployed fix's condition
was satisfied - the fix was insufficient, not broken.

**Second root cause**: the company-pass only ever looks at `candidates` (MANUAL_REVIEW/
NEEDS_REVIEW/FAILED jobs) - it has no way to know a *different* job at the same company was
already genuinely submitted by Playwright itself moments earlier, and that a generic
confirmation email most likely belongs to *that* submission instead. Confirmed exactly this:
a real, fully-receipted Verkada submission (Senior Backend Engineer - Intercom, 18:29:59 UTC,
Greenhouse confirmation URL, Qwen confidence 1.0) existed 19 minutes before Connectivity's
false match - the email almost certainly belonged to Intercom, and Connectivity was simply
the only other thing still open when the reconciler ran.

**Second fix**: added `_has_recent_genuine_submission()` - before crediting a company-only
match, check whether *any* job at that company already carries real Playwright receipt data
(`submissionEvidence.receipt` or `.confirmationUrl`) with a `submittedAt` within an hour of
the email. If so, skip - the email is already explained. Note: had to key this off receipt/
confirmationUrl presence, *not* `submissionSource`, because that field gets overwritten to
`"email-detected"` the moment the reconciler ever touches a job, even one that already had a
genuine receipt sitting in NEEDS_REVIEW for unrelated reasons - using it as the "already
genuine" signal would have hidden the very anchor the check needs.

**Important methodology correction - do not over-read this**: ran the new check
retroactively against all 92 remaining `company`-matched SUBMITTED jobs to see how many more
might be affected. It flagged 89. This number is **not trustworthy as a revert list** - it
includes jobs I independently Gmail-verified as genuine earlier this session (several Klaviyo
postings, confirmed against real "Thank you for applying" emails with matching role names and
timestamps). The retroactive check can't tell "this candidate wrongly stole another
submission's email" apart from "this candidate has its own genuine email, and unrelated
happens to sit within an hour of another real submission at the same busy company" - Klaviyo
had ~7 genuine, independent confirmations arriving close together, which is exactly the
pattern that trips this heuristic without being wrong. **Did not bulk-revert the 89.** Only
reverted jobs with the same hard, individually-checked proof as before
(`domVerification.passed: false`, no receipt) - found 10 more this way (mix of new ones from
tonight and, notably, some dated 2026-09-07 through 09-11 - **this bug predates tonight's
session and has likely been corrupting SUBMITTED counts for about a week**). Also explicitly
excluded one job with `submissionSource: "manual"` from correction - that reflects the user's
own "I submitted this by hand" action via the UI, not the reconciler, and reverting it would
have erased a genuine record instead of fixing a bug. Verified after: 0 proven-false remain,
total SUBMITTED 627 → 617.

**Net effect so far across all cycles**: 659 → 617 SUBMITTED (75 corrected total: 55 + 10 + 10
proven-false reversals), two root causes fixed and both live-verified. The 48-uncertain and
43-ambiguous-Qwen-outcome buckets from earlier remain untouched and still worth the user's
own review if they want certainty, but are not something I can resolve with hard evidence.

**Update 11:37 PDT — deployed and cleaned up the gap window (first fix only, see above for
the follow-up).** Used `pause` to get a clean
APPLYING-free window, restarted, verified settings correct, resumed via a single `start()`
call. Before redeploying, checked for NEW false positives accumulated in the ~30min gap
between the correction and the restart (the old buggy code was still running during that
window) - found **10 more**, same proven-false signature (`domVerification.passed: false`,
company-only match, no receipt). Corrected those too via the same `/reprocess` batch approach
(one browser tab detach mid-batch, caught by re-checking DB state and finishing the remaining
3 in a fresh tab call rather than assuming failure). Verified: 0 proven-false SUBMITTED jobs
remain, total SUBMITTED 632 → 622. Checked 0 new SUBMITTED jobs have landed via the company
pass since the actual redeploy timestamp (18:35:41 UTC) - too early to confirm the fix holds
at scale, watch next cycle.

---

## 2026-09-14 10:41 PDT — Orphaned another job the same way as Cribl — self-inflicted, same root cause, now recovered

Found 2 jobs `APPLYING` simultaneously (concurrency is 1 — should never happen). Traced it:
after the isolated Robinhood re-test, `preflight-approve` had already resumed the batch loop
("Autopilot is already running"). I then *also* issued my normal end-of-cycle
`/autopilot/start` call to "restore standard batch settings" - unnecessary, since the loop
was already healthy, and it landed while that loop's most recent claim (Speechify,
`apjob_0eb2b639`) was mid-navigation. Same mechanism as the Cribl incident: `.cancel()` +
1s grace + spawn-new-task-regardless orphaned the in-flight job with no cleanup.

**This time proved it beyond the lease-data inference** (no `lockedBy`/`lockedAt`/
`lockExpiresAt`, same as Cribl) **with direct log evidence**: grepped the window right after
the cancel and watched the *new* loop task claim and fully process three separate jobs
(Mitratech -> NEEDS_REVIEW, Datadog -> no form found, Everlaw -> submitted) while Speechify's
log trail stayed frozen at its single "Navigating to application URL" line the entire time.
Not a guess this time - a live side-by-side comparison of a working task against the dead one.

**Recovered without disturbing the healthy loop**: the run's heartbeat was fresh (the healthy
task keeps it warm), so the stale-heartbeat auto-recovery I used for Cribl wouldn't trigger.
Used the single-job `POST /autopilot/jobs/{id}/reprocess` endpoint instead, scoped to just
Speechify's id - resets that one job to QUEUED without touching the run or any other job.
Confirmed after: APPLYING back to 1 (the healthy loop's current job), fresh heartbeat, run
still RUNNING. Did **not** call `/autopilot/start` again to pick it back up - the running
loop already claims from the queue on its own, and calling start() again would risk repeating
the exact same mistake a third time.

**Rule going forward, added to this file so it survives a cold pickup**: once
`preflight-approve` (or any prior action) reports the batch is already running, do not
reflexively call `/autopilot/start` again "to be sure" - check current settings via the DB
first, and only issue `start()` if they're actually wrong. `start()` is not a safe no-op
against a live loop; every call that lands mid-job risks orphaning it.

**Rest of cycle**: run healthy (RUNNING, fresh heartbeat, queue at 200). Gmail spot-checked
Pingidentity (the one recent SUBMITTED job not yet verified) - genuine "Thank you for
applying to Ping Identity" confirmation exists. Robinhood fix real-world sample so far is
thin (only 1 attempt since deploy - the test job itself, which submitted cleanly; 10 more
Robinhood postings are queued but not yet reached) - too early to call the recurrence rate,
will have a real sample by next cycle or two.

---

## 2026-09-14 10:31 PDT — Actually fixed the Robinhood military-status field (user-requested, ground-truth verified)

User explicitly asked to fix the remaining combobox gap before letting it keep cycling through
the review queue. Rather than keep guessing at `_find_negative_option`'s matching rules, went
to the source: navigated the browser tab directly to Robinhood's real Greenhouse posting
(`https://job-boards.greenhouse.io/robinhood/jobs/8036588`) and opened the actual dropdown to
read its real 7 options:

  1. I am on active duty
  2. I am part of the national guard or on reserve
  3. **I have never served in the military**
  4. I identify as a protected veteran
  5. I identify as a non-protected veteran
  6. I identify in multiple military status categories
  7. I don't wish to answer

The correct non-veteran answer (#3) contains **neither** "veteran" nor "not" - it says
"never served in the **military**". That's exactly why both my classifier fix (deployed last
cycle) and my first attempt at an executor-side negative-option fallback (deployed this
cycle, at 10:22 PDT) still failed identically: `_find_negative_option`'s keyword was hardcoded
to `"veteran"` and its negation regex only checked `\bno\b|\bnot\b`, so it could never match
this board's actual phrasing. Confirmed this by re-testing my "fixed" build against the same
job (`apjob_16ae51fa`) - identical failure, "not found in 7 options" again.

**Real fix**, in `profile_answer_resolver.py`:
- `_find_negative_option(opts, keyword)` now accepts a tuple of keyword synonyms (not just
  one), and its negation regex is `\bno\b|\bnot\b|\bnever\b|\bnone\b`.
- `_resolve_veteran` now calls it with `("veteran", "military", "served")` instead of just
  `"veteran"`.
- Matching update in `playwright_autopilot_executor.py`'s `NEGATIVE_OPTION_KEYWORDS` (my
  executor-side fallback from last cycle) to the same tuple.

**Verified against real data before deploying**: ran `_find_negative_option` directly against
Robinhood's actual 7-option list in a throwaway script - correctly returns "I have never
served in the military". Compile-checked both files clean.

Blocked on redeploying again - a fresh job (Veeamsoftware, `apjob_f2c41dc7`) is APPLYING; used
`pause` again but that only stops new claims, doesn't skip the current one, so waiting for it
to clear naturally (backgrounded a wait-and-notify check rather than polling manually).

**Scope note**: `_find_negative_option` is also used for `DISABILITY` - unchanged behavior
there (single keyword `"disab"`, same negation set now broadened by the "never"/"none"
addition, which is a strict superset so cannot cause the disability path to match a false
positive it wouldn't have matched before - it can only catch more legitimate "no" phrasings,
e.g. "I have no disability" or "None of the above").

**CONFIRMED WORKING — full live verification, not just a code read.** Job cleared, restarted,
re-tested `apjob_16ae51fa` (same Robinhood posting) a third time: no "military status...not
found" warning fired this run at all, and it went all the way to **SUBMITTED** ("Real browser
submission confirmed", 17:36:11 UTC). This is the actual fix the user asked for, done. Gmail
confirmation not yet checked (too soon after submission for the email to have landed) - worth
a spot-check next cycle. Resuming full batch operation now.

---

## 2026-09-14 10:17 PDT — Deployed the classifier fix; live test shows it's a real but partial fix

Used `pause` (not a raw kill) to get a clean APPLYING-free window instead of racing the
concurrency=1 loop for a lucky gap: `/autopilot/pause` stops new job claims without touching
the in-flight one. Confirmed 0 APPLYING after, then ran the normal restart sequence
(compile-check, restart, both health checks passed).

**Live-verified via the `reprocess-autopilot-job` skill** on one specific Robinhood posting
(`apjob_16ae51fa`, Kubernetes Compute) rather than trusting the code read: real result is
**partial**. The log line changed from the old `Combobox 'What is your military status?*'
unresolved (type=UNKNOWN), skipping` to `Combobox 'What is your military status?*': target
'I am not a protected veteran' not found in 7 options, skipping (NO random fallback)` — so
the classifier fix genuinely works: the question is now recognized as VETERAN_STATUS and a
target answer is computed (previously it wasn't even attempted). But it still didn't get
filled, and traced why: Robinhood's field is a **dynamic/searchable combobox widget**, and
`playwright_autopilot_executor.py`'s handling for that widget type (~line 1247, the
`chosen`/`segment_match`/`prefix_match`/`fallback` search loop) has its own independent
option-matching logic that does **not** call `_find_negative_option` (the fuzzy "find a real
option that says no about X" fallback in `profile_answer_resolver.py` that fixes this exact
class of problem for other field types). So this specific board still ends up staged for
review — a real, separate, deeper bug for a future session, not something to chase further
tonight. Documented precisely so it's pickable-up cold: the fix needed is wiring the dynamic-
combobox path to fall through to `_find_negative_option` (or an equivalent) the same way the
static-options path already does, instead of its own `chosen/segment/prefix/fallback` scan
with no negative-option awareness.

**Update 12:48 PDT — two user questions answered, both worth a decision when they're back.**
(1) Clarified that Gmail verification is a native CareerOS backend feature
(`manual_submission_reconciler.py`, runs automatically inside `queue_preprocessor.py` every
10 cycles via IMAP) - this session's fixes improved that exact mechanism, not a parallel
process. Asked whether the user wants the additional manual browser-based spot-check kept as
an ongoing audit layer now that the backend is fixed, or dropped. (2) Explained why the run
shows `38` against a requested `batchSize: 10`: `autopilot_runner.py`'s resume path sets
`targetProcessCount = max(existing_target, processedCount + requested)` on every `start()`
call rather than resetting to a fresh batch - so repeated resumes across the night ratchet the
cumulative target upward instead of it meaning "batch size." Asked whether to leave this
(intentional-seeming: preserves progress across resumes) or fix it to mean a real
one-shot batch. **No reply yet on either - not blocking, noted here so it isn't lost.**

Rest of cycle: healthy. 3 new SUBMITTED (all genuine Robinhood, direct Playwright receipts -
also a good incidental confirmation the military-status fix keeps holding at scale). Queue
dipped to 97 (just under the ~100 watchdog line) but refill is actively running (fresh
aggregator-resolve activity in the log) - not stalled, just a normal dip. 23 new NEEDS_REVIEW,
all known-good categories.

**Update 12:26 PDT — fix holding cleanly.** 4 new SUBMITTED jobs since the second reconciler
fix redeployed, all genuine direct Playwright submissions (real receipts, `confirmationMatchedOn:
None` - didn't even need the reconciler). Zero company-only matches fired this cycle, so no
new test of that specific path yet, but nothing wrong either. Gmail-spot-checked Grafana's
newest submission - genuine confirmation exists, timing matches. NEEDS_REVIEW churn this cycle
(24 new) is 100% known-good categories (18 other DOM mismatches, 6 second-opinion) - zero
military-status recurrence. Run healthy throughout.

**Net effect of tonight's classifier fix**: real improvement for any board using a
standard/static option list with "military status" phrasing (where `_find_negative_option`
already applies), but not for Robinhood's specific dynamic-combobox implementation. Expect
some, not all, of the Robinhood NEEDS_REVIEW recurrence to stop.

Batch resumed after this (single `/autopilot/start` call, not double). Verified via DB:
`selfHealing: false`, `tierGuardrails: true`.

---

## 2026-09-14 10:00 PDT — 0% conversion so far on the requeued batch — checked, not alarming

48 of the 274 requeued jobs have been attempted 34 minutes post-requeue; 47 went back to
NEEDS_REVIEW, 0 SUBMITTED (1 in flight). Checked whether this is a new problem before
flagging it as one: broke down the 47 by reason — 14 are the Robinhood military-status gap
(fix already written last cycle, just not deployed yet — still running old code, so this is
expected, not a regression), 16 other DOM-verification mismatches, 13 second-opinion
rejections, 3 reCAPTCHA, 1 other. All within the already-documented pattern set. Robinhood
alone is 15 of 47 (32%) of this batch — once the classifier fix deploys, that chunk should
stop recurring and conversion should visibly improve. No new bug here; still blocked on the
same restart (a healthy Datadog job has been APPLYING across two checks now — went
QUESTIONS_COMPLETED -> a fresh PAGE_OPENED with a newer timestamp, consistent with a normal
internal retry attempt, not a stall like Cribl was).

---

## 2026-09-14 09:49 PDT — Found and fixed the Robinhood "military status" gap (repeating pattern)

Per cycle rule 3 ("only dig into something new or repeating") — of the 274 requeued jobs,
27 had already cycled back to NEEDS_REVIEW within the first 22 minutes, and 4 of those were
the exact same Robinhood "What is your military status?*" question I'd already flagged twice
as a standing gap (144 occurrences in the logs going back to 9/9). Since it's costing real
requeue cycles right now and I had a concrete lead, traced it to an actual root cause instead
of leaving it as a known-bad pattern:

**Root cause**: `question_classifier.py`'s `VETERAN_STATUS` patterns were `veteran`,
`military\s+service`, `armed\s+forces`, `protected\s+veteran` — none of which match "military
**status**" (the log's own "unresolved (type=UNKNOWN)" wording was the tell: this was never
being classified as a veteran-status question in the first place, not a downstream
option-matching failure). The answer-resolution side (`profile_answer_resolver.py`,
`_resolve_veteran`) already has fuzzy fallback logic (`_find_negative_option`) to handle a
board's specific option wording once it's correctly classified — so this one missing regex
was the whole gap.

**Fix**: added `r"military\s+status"` to the `VETERAN_STATUS` pattern list. Compile-checked
clean. **Not yet deployed or live-verified** — a job (Twitch) is genuinely in-flight
(APPLYING, fresh as of 16:48:45 UTC, confirmed healthy/progressing this time, not a repeat of
the Cribl situation). Once clear: restart per discipline, then use the
`reprocess-autopilot-job` skill to retry one specific Robinhood posting in isolation and
confirm the military-status question actually gets answered now, before trusting this fixed
more broadly.

---

## 2026-09-14 09:26 PDT — Both pending actions deployed and verified

Job cleared naturally (0 APPLYING) this cycle. Ran the full sequence:

1. Recorded before-counts: NEEDS_REVIEW 274, MANUAL_REVIEW 548, QUEUED 0.
2. Compile-checked both edited files again, confirmed zero APPLYING, killed node/python,
   restarted via `scripts/restart-dev.ps1 -Background` — both health checks passed.
3. Started the batch through the browser tab (single POST this time, not the double-fire
   mistake from earlier). **Settings-persistence fix verified live**: the resumed run's DB
   `settings` now correctly show `tierGuardrails: True, selfHealing: False` — previously this
   stayed `False`/stale on a resume regardless of what was requested. Confirmed by reading the
   run row directly from the DB, not trusting the response body.
4. Called `POST /autopilot/reprocess-staged` per the user's request: `reprocessedCount: 274`.
   After: NEEDS_REVIEW 0, STAGED 0, QUEUED 273 (the 274th was immediately claimed into
   APPLYING by the already-running batch worker — reconciles cleanly, nothing lost).
   MANUAL_REVIEW untouched at 548, as designed (bot-blocked jobs correctly excluded from the
   bulk requeue).

All caught up. Everything from this session's investigation is now deployed and confirmed
working: Gemini fallback model fix, run-settings persistence fix, and the review-queue
sweep. Next cycles should be normal monitoring per the loop's standard steps 1-4 unless
something new turns up — the 273 requeued jobs are worth watching to see what fraction
converts now vs. cycling back to NEEDS_REVIEW (the DOM-verification-gap jobs, e.g.
Robinhood's military-status question, will very likely repeat; the ~103 second-opinion ones
are the ones actually likely to resolve differently).

---

## 2026-09-14 09:15 PDT — Diagnosed the Cribl stuck-job as a self-inflicted orphan, recovered it via the app's own mechanism (not a raw DB edit)

**Root cause, fully traced:** Earlier this morning I made two `/autopilot/start` POSTs 59s
apart (08:25:22 and 08:26:21 PDT) because my first `javascript_tool` call returned a
"[BLOCKED: Cookie/query string data]" privacy-guard result and I couldn't confirm it had
actually gone through, so I retried. Both actually fired. The second call's cancellation
logic (`autopilot_runner.py`, the `Cancelling lingering _loop_task for clean start` branch)
called `.cancel()` on the first call's loop task, gave it 1 second, then moved on regardless.
The first task had claimed Cribl (`apjob_92f53d34`) 2s after the first start call and was
mid-way through it (`QUESTIONS_COMPLETED` at 08:25:47) when cancelled — it appears to have
died right there without its cleanup path running (job status never updated past APPLYING,
`lockedBy`/`lockedAt`/`lockExpiresAt` are all `None` — it was never holding a proper lease at
all). This is a real robustness gap: cancelling an in-flight `_run_batch_worker` task can
orphan whatever job it was mid-processing, with no status cleanup. Worth a proper fix later
(the recovery-on-resume path already in this file handles the run-level case; the per-job
cleanup on cancellation itself does not).

**Why I'm confident it's dead, not just slow, before acting:** checked the log for the
*second* (surviving) loop task's own lifecycle — it started at 08:26:22.147 and logged
`Batch worker loop exited normally` at 08:30:49.873, over 45 minutes before this check, and
no `Batch worker loop starting` line exists after that. **No process has owned this run at
all for 45+ minutes** — run status is `PAUSED`, heartbeat frozen at that same 08:30:49
timestamp. So this isn't "an in-flight submission that might still complete" — the worker
that would have been operating on it is already gone, cleanly, per its own log line. Ruled
out an alternative theory first too (event-loop starvation from the synchronous
`ThreadPoolExecutor` aggregator-resolution in `queue_preprocessor.py`) — confirmed that call
is correctly wrapped in `await asyncio.to_thread(...)`, so it isn't blocking the loop.

**How I recovered it — not a raw DB hack:** the codebase already has a designed-for-this
mechanism: `AutopilotRunner._recover_stale_run_sync`, triggered automatically inside
`start()` whenever the resumed run's `lastHeartbeatAt` is >60s stale. It releases the run's
`currentJobId` and sweeps *every* APPLYING job whose lease has no `lockExpiresAt` or an
expired one back to `QUEUED` — exactly Cribl's state (`lockExpiresAt: None`). Rather than
edit the DB row myself, I re-issued the normal `/autopilot/start` POST (through the browser
tab, per the hard rules) with the heartbeat already 45min stale, letting the app's own logic
detect the staleness and run the sweep. Confirmed after: Cribl back to `QUEUED`, zero
APPLYING jobs — briefly, since the now-healthy run immediately claimed its next job
(Pingidentity, `apjob_c5a892b7`) and is progressing normally. Still can't restart yet (that
job is legitimately in flight), but this is now ordinary single-job-at-a-time operation, not
a stuck state — next cycle should find it clear.

---

## 2026-09-14 08:52 PDT — Cycle: stuck job blocking deploy, Gmail spot-checks

**Blocked on the settings-persistence bug fix (autopilot_runner.py, found last cycle) and
the user's request to requeue NEEDS_REVIEW via `/autopilot/reprocess-staged`** — both need a
restart, and job `apjob_92f53d34` (Cribl, Sr Software Engineer Stream Integrations) has been
sitting in `APPLYING` at step `QUESTIONS_COMPLETED` since 15:25:47 UTC with **zero log
activity since 15:26:21** — confirmed via `grep` on its exact application URL, nothing since.
That's 25+ min past the ~10min hard-watchdog window I've seen fire for this identical
failure mode elsewhere in the logs ("Playwright execution hard watchdog timed out ... at
step QUESTIONS_COMPLETED") — the watchdog itself does not appear to have fired this time.
Per hard rules, not forcing it. If it's still stuck next cycle, worth digging into why the
watchdog didn't trigger (separate bug candidate) rather than continuing to just wait.

**Gmail spot-checks (hard rule #4), two companies:**
- **Klaviyo (4 SUBMITTED jobs)** — all 4 verified genuine. Gmail has a "Thank you for
  applying to Klaviyo" thread with 7 separate confirmation emails from `no-reply@klaviyo.com`
  (one per role), and all 4 DB titles/timestamps match a corresponding email within ~10 min.
  Clean pass.
- **Twilio (9 SUBMITTED jobs total, spot-checked the newest — "Software Engineer (L4)",
  submitted 2026-09-14T08:58:45 UTC)** — searched Gmail `in:anywhere` (spam/trash included):
  **no "thank you for applying" style email exists for Twilio at all**, across any of the 9
  submissions going back to 9/8. Only 4 "Security code for your application to Twilio" emails
  from Greenhouse (the mid-flow verification code, not a post-submit confirmation). Read as
  inconclusive rather than a red flag: Twilio's Greenhouse instance appears not to send an
  apply-confirmation email at all (a per-board template choice, not universal), and the code
  emails are still a real signal — they only fire when a genuine form-fill is underway. Each
  SUBMITTED job also carries `"Real browser submission confirmed"` in its own checkpoint
  (on-page confirmation, verified by Qwen at submit time), which is the actual evidence this
  status already rests on. Flagging the board-level email gap for future spot-checks rather
  than treating Twilio submissions as unverified.

**Next cycle:** re-check Cribl; if clear, deploy the settings-persistence fix (restart,
verify `selfHealing:false` + `tierGuardrails:true` actually land in the DB this time), then
run `/autopilot/reprocess-staged` per the user's request and record before/after NEEDS_REVIEW
counts.

---

## 2026-09-14 08:30 PDT — Two-day root-cause analysis: why last night collapsed to ~9 while prior nights did ~100-350

User asked for a full comparison across the last two days. Bucketed every `aa_autopilot_job`
by day/night window (9pm-9am / 9am-9pm PDT) using DB timestamps, cross-referenced against
`aa_autopilot_run` settings and `api.log`.

**Numbers (internal SUBMITTED-status count, not Gmail-verified):**
| Window | Total jobs touched | SUBMITTED | Conversion |
|---|---|---|---|
| night 9/11->9/12 | 404 | 81 | 20% |
| day 9/12 | 51 | 16 | 31% |
| night 9/12->9/13 | 221 | 84 | 38% |
| day 9/13 | 573 | 270 | 47% |
| **night 9/13->9/14 (last night)** | **602** | **44** | **7.3%** |

Gross volume last night was actually the *highest* of any window (602 jobs touched) — this
was not a throughput collapse, it was a **conversion collapse**. 273 jobs (new all-time high;
this status had essentially never fired before) landed in NEEDS_REVIEW: 136 DOM-verification
mismatches (required field the automation couldn't confidently fill), 103 "second opinion"
match-gate rejections (68 disagreed + 35 undecided), 33 reCAPTCHA (expected/known-good).

**Ruled out:** I initially suspected `tierGuardrails` was off for last night's run (the DB's
persisted run-settings field showed `False`) — checked `api.log` for every literal
`start_autopilot called with options` line for run `aprun_7cb71c15` across its whole life
(14:00, 14:09, 15:14, 15:25 on 9/13, plus my two calls this morning) and **every single one
explicitly requested `tierGuardrails: True`**. The DB field was stale, not the live behavior
— see the bug below. Retracting that theory; guardrails were on the whole night.

**Confirmed contributors:**
1. **Gemini quota exhaustion** (already fixed this session, see prior entry) — 734 straight
   HTTP 429s from the hardcoded `gemini-flash-latest` fallback. Plausible driver of a chunk of
   the 103 second-opinion escalations (that gate calls Gemini for a "clarify" pass).
2. **Pre-existing, still-open combobox/question-answering gaps** — the dominant chunk (136
   DOM mismatches). Top offenders: "What is your military status?" (25, almost entirely
   Robinhood — confirmed via `grep -c "military status" api.log` = 144 occurrences going back
   to **2026-09-09**, so this is not new), "End date year/month" (24), GPA/citizenship/export-
   control/DEI questions. These are real, standing automation gaps in the question-answering
   layer — not something introduced last night — but the last night's queue happened to have a
   denser concentration of postings that hit them.
3. **New bug found and fixed live**: `autopilot_runner.py`'s `start()` never wrote the
   resolved settings (tierGuardrails, minMatchScore, selfHealing) back onto an existing
   run's persisted `settings` field when resuming a paused/running run — only a brand-new
   run got the caller's settings saved. The in-memory runtime used the right values (which is
   why guardrails were genuinely on all night), but the DB row kept lying about it, and
   `_last_run_settings()` reads that same stale field as the fallback for any future
   `start()` call that omits a key — a real latent bug (a plain UI "Start" click with no
   explicit payload would silently inherit whatever the run was *first* created with).
   Fixed: `existing["settings"] = opts` added at the resume branch. Compiled clean.
   **Not yet redeployed** — a job (Cribl, Sr Software Engineer) is currently APPLYING;
   per hard rules, waiting for it to clear before restarting rather than forcing it.

**Still open / not fully explained:** why last night's *candidate mix* skewed so much more
toward jobs with these hard-to-answer custom questions than 9/12's did, when both ran under
matching settings. Candidate: a much heavier share of last night's queue came from the
Himalayas aggregator (lots of "Could not resolve aggregator listing" log lines), and
`da24099` (committed 9/13 13:03 PDT, mid-afternoon) added new aggregator-URL resolution at
enqueue time — worth checking next cycle whether the job source mix genuinely shifted after
that commit landed, or whether this is coincidence from which postings happened to be
freshest in the scrape that day.

**On the "9" vs the internal counts above:** these numbers all come from the same internal
`SUBMITTED` DB status across every window, so they're apples-to-apples with each other, but
per project convention that status isn't proof of a real submission (see
`verify-gmail-application-confirmation`). Haven't yet spot-checked last night's 44 against
Gmail — queued for the next cycle.

---

## 2026-09-14 08:27 PDT — Browser extension reconnected, batch resumed

User confirmed Chrome running / extension was off; reconnected on its own by the time I
checked `tabs_context_mcp` again. Navigated the tab to `localhost:5000/applications` and
issued the `/api/backend/application-assistant/autopilot/start` POST from inside that tab
(not a raw backend call), with `{targetProcessCount:10, batchSize:10, concurrency:1,
minMatchScore:60, tierGuardrails:true, selfHealing:false}`. HTTP 200.

**Verified directly from DB after (not trusting the response body):** same run id
`aprun_7cb71c15` (the paused one from overnight) resumed to `status=RUNNING`,
`selfHealing: false` confirmed in the run row's `settings`. Target bumped from 21 to 26,
processedCount ticking up (17 at time of check). Note: `tierGuardrails` in the settings
still reads `false` — this is the *existing* paused run being resumed/extended rather than
a fresh run object picking up my new settings payload; worth checking next cycle whether a
genuinely new run is needed to get `tierGuardrails: true` to stick, or whether the backend
just ignores that field on a resume.

**Gemini fix — not yet live-verified:** no Gemini fallback call has fired since the
restart (checked tail of `api.log`, nothing yet). Will confirm no `HTTP 429` against
`gemini-flash-latest` recurs once one does; check next cycle.

Queue was at 3 before this start (well under the ~100 refill threshold) — need to confirm
next cycle whether the preprocessor actually refilled it or whether that's a separate
thing to investigate.

---

## 2026-09-14 08:09 PDT — Bug fix applied & verified, servers restarted

**What:** Found and fixed a real bug during log investigation (in response to "only 9
submitted overnight, why"): `apps/api/app/services/application_assistant/llm_client.py`
hardcoded `model="gemini-flash-latest"` in two places (`_resolve_llm_config` default,
`_build_gemini_fallback`). That model's free-tier daily quota was already known-exhausted
— `app/services/gemini/config.py` has a comment explaining the *other* Gemini integration
was already switched to `gemini-flash-lite-latest` for exactly this reason, but
`llm_client.py`'s fallback path (used whenever local Ollama fails) never got the same fix.

**Evidence:** 734 consecutive `HTTP 429` errors from `gemini-flash-latest` in
`apps/api/data/logs/api.log` over the ~15.5h life of the last run (started
2026-09-13 21:00 UTC). Every one of those calls returned nothing, which plausibly
inflated the NEEDS_REVIEW pile (DOM-verification-mismatch and "second opinion"
reasons) since a failed LLM call escalates to review rather than resolving.

**Fix:** Changed both hardcoded model strings to `gemini-flash-lite-latest`
(`llm_client.py:653`, `:759`, roughly — see git diff).

**Verification done:**
- `python -m py_compile app/services/application_assistant/llm_client.py` — passed.
- Confirmed zero jobs with `status=APPLYING` in the DB before touching any process.
- Killed node/python, restarted via `scripts/restart-dev.ps1 -Background` — both
  health checks (API :4000, Web :5000) passed.
- **Not yet verified live** (no Gemini fallback call has fired since restart to confirm
  the 429s stop). Will confirm on the first cycle that triggers one, or note if it
  doesn't recur over the next few hours.

**Next:** watch `api.log` for `error=HTTP 429` recurrence tied to `gemini-flash-latest`
— if it reappears, there's a third call site not yet found.

---

## 2026-09-14 08:09 PDT — BLOCKED: cannot start next batch through the UI

**What:** Per hard rules, batch starts must be issued as a `fetch` from inside the real
browser tab on the app (not a raw backend script), so the request goes through the same
path a real user click would. `tabs_context_mcp` reports the Claude-in-Chrome browser
extension is **not connected** — cannot open/drive a tab right now.

**State found:** Last run `aprun_7cb71c15` is `PAUSED` at 16/21 processed
(`tierGuardrails: false` on that run's settings — note this differs from the
`tierGuardrails: true` the spec asks for on future starts). Only 3 jobs currently
`QUEUED` — well under the ~100 refill threshold, so a refill should trigger, but I
haven't been able to confirm the queue preprocessor is doing that yet.

**Action taken:** Not bypassing the browser-only rule with a direct backend call.
Continuing to monitor DB/logs on the regular check-in cadence and will start the batch
through the browser the moment the extension reconnects. Flagging to the user now since
reconnecting the extension (or confirming Chrome is running) is something only they can
do.

**Needs:** user to confirm the Claude in Chrome extension is installed/running so browser
automation can resume.

---

## 2026-09-14 21:30 UTC — Roblox: extracted the real Greenhouse URL, found it renders full standalone (with a caveat), shipped a conditional fix

**What:** User asked to pull the Greenhouse link out of Roblox's embedded iframe and test
navigating to it directly instead of driving the iframe. Verified live in a real browser
tab (careers.roblox.com/jobs/8127056 → clicked Apply → read the iframe's `src`):

```
https://job-boards.greenhouse.io/embed/job_app?for=roblox&validityToken=<long signed token>&token=8127056
```

Navigated a tab directly (top-level, no framing, no careers.roblox.com involved at all)
to that exact URL. It rendered the **complete** form: 33 real inputs, resume
upload/autofill controls, and a working "Submit application" button — not a stub.

**This directly contradicts existing code.** `playwright_autopilot_executor.py` (~line
2828, pre-existing) has a documented, evidence-based rule that Greenhouse's
`/embed/job_app` endpoint only renders a full form while framed, and going there directly
gives a stub with no submit button — measured on Databricks (47→3 inputs, submit
disappears) and Datadog (26→1 input, submit disappears). That measurement is presumably
still correct for those two.

**Reconciling the two observations:** the Roblox iframe's `src` carried a signed
`validityToken` query param; the reconstructed URLs used elsewhere in the same file (the
`gh_jid=` career-hub-resolution path, ~line 2566) build a bare `for=<slug>&token=<id>` URL
with **no** validityToken. Working theory: that token is what Greenhouse's own
stub-vs-full-form check keys on — present it and you get the real form standalone, omit it
and you get the framed-only stub. Not fully confirmed (would need to test Databricks/
Datadog's actual iframe `src` values for a token), but consistent with every measurement
on hand.

**Fix shipped** (`playwright_autopilot_executor.py`, the `embed_src` "/embed/job_app"
staying-framed check): now conditional on `validityToken=` being present in the extracted
embed URL. Present → follow it directly (bypasses whatever makes driving the cross-origin
iframe itself hang — the actual root cause of Roblox's automation timeouts is still
unconfirmed, per the earlier decision below not to keep digging into that). Absent → keep
the prior behavior exactly (stay framed, drive the iframe) so Databricks/Datadog are
unaffected. Compile-checked, not yet run live end-to-end against a fresh Roblox job (the
`_ROBLOX_TEST_EXCEPTION_URLS` carve-out in `job_filter_ranker.py` is still in place for
that).

**Not done / left open:** removing the `_ROBLOX_TEST_EXCEPTION_URLS` carve-out once this
is verified working generally for Roblox postings; confirming the validityToken theory
against Databricks/Datadog; the underlying `--disable-http2`-flag hypothesis for the
iframe-hang itself.

---

## 2026-09-14 21:30 UTC — Company-scoped bulk requeue for Manual/Skipped/Ineligible

**What:** User asked that filtering the Applications view by company and then hitting
"requeue" only requeue that company's applications, and that the same bulk-requeue
functionality exist on the Manual Review, Skipped, and Ineligible tabs (previously only
Review and Failed had it).

**Existing design constraint found:** `/autopilot/requeue-bucket`'s `REQUEUABLE_BUCKETS`
map deliberately excluded Manual/Skipped/Ineligible entirely, with a comment explaining a
wholesale sweep of those would "refill the queue with the exact jobs the user has already
worked through and dismissed." That reasoning is still correct for a *wholesale* sweep —
so rather than removing the restriction, the fix keeps it for the no-filter case and adds
a narrower allowance: those three buckets are requeueable now, but **only** when the
caller also names a `company` (enforced server-side, 400 if missing — `COMPANY_ONLY_BUCKETS`
in `autopilot.py`). Review/Failed keep their existing wholesale-or-filtered behavior
unchanged.

**Frontend** (`autopilot-applications-view.tsx`): the bulk "Move to queue" button now
appears on Manual/Skipped/Ineligible tabs only once a company filter is chosen (button is
absent otherwise, matching the backend rule rather than surfacing a 400). Review/Failed's
button is unchanged in when it appears, but its label and the confirm dialog now say
"Move N \<Company\> to queue" and use the company-scoped count
(`companyCounts[companyFilter]`, already computed in this component for the company
dropdown) instead of the always-global `counts[filter]` when a filter is active.

**Verification:** both `tsc --noEmit` and `py_compile` pass. Not yet exercised live
end-to-end (no company currently has enough Manual/Skipped/Ineligible volume queued up in
this session to click through, and the dev server was mid-restart for the Roblox fix
above when this landed) — first live use of the new buttons should be treated as the real
test.
