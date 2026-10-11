---
name: autopilot-night-batch-loop
description: Autonomous overnight batch application monitoring, fresh-jobs-first intake (postings from the last 24 hours are pulled and applied to before older queued jobs), a 30-minute audit loop, deterministic question resolution, mid-run fix deployment, company cap preservation and a morning handoff for CareerOS.
---

# Autopilot Night Batch Loop Skill

Autonomous, unattended or monitored overnight batch application processing for CareerOS with fresh-jobs-first intake, continuous safety validation, an audit of every job on each 30-minute tick, deterministic question classification, and strict per-company pacing.

## When to Use

Trigger this skill when:
- The user requests to "run night job", "continue with the night loop", or "monitor overnight batch".
- The user requests an autonomous run with failure/review checking every ~10 applications.
- The user asks to pull the latest (last 24 hours) jobs and apply to them ahead of the existing queue.
- Reviewing `NEEDS_REVIEW` and `MANUAL_REVIEW` classifications to fix deterministic questions.
- Verifying company quotas (company cap pacing) and Browse Jobs exclusion during batch runs.

---

## Loop Lifetime — runs until the user explicitly breaks it

The night loop never ends on its own. It stops only when the user explicitly says to stop/break/end the night loop.

- **Runner side**: one `POST /application-assistant/autopilot/start` run is already continuous. When `processedCount` reaches `targetProcessCount`, the runner resets its counters and starts the next batch instead of finishing. If the run is found `PAUSED` (queue drained), `STOPPED` or `FAILED` without the user asking, do a fresh 24-hour pull and start it again (`{"targetProcessCount": 100, "concurrency": 1}`). The only exception is a stop-the-run defect (see Step 2b), which you must fix before restarting.
- **Agent side**: monitoring must survive between chat turns. Arm a recurring wake-up with the `loop` skill (local: a background PowerShell loop printing a sentinel such as `AGENT_LOOP_TICK_nightloop` every ~30 minutes, watched with `notify_on_output`). On every tick run the audit, the fresh-pull check and the review-question check below. Check the terminals for an existing loop first; never run two.
- **Breaking the loop**: only on an explicit user request. Then kill the sentinel loop's PID, `POST /application-assistant/autopilot/stop`, and confirm both stopped.

### Before the user leaves
Settle these while the user is still around; overnight nobody can answer them:
1. **Boards after Greenhouse/Lever/Ashby run out.** With `submittableBoardsOnly` on, the runner moves to Workday, Phenom and aggregator postings once no submittable job is free of a company hold. Those almost all end in `MANUAL_REVIEW` (Workday sign-in walls, no form on the page, bot walls). Ask whether to let it keep going (it triages the backlog into the manual list) or to stop once starved (see "When the submittable boards run dry").
2. **Pending answers.** Open `GET /application-assistant/autopilot/readiness` and ask the top questions by `unblocksAlone` now (Step 4b) instead of carrying them to the morning.
3. **Browse Jobs alignment** (Step 6) once; it does not need repeating every tick.

Open the night's entry in `NIGHT_BATCH_DECISIONS.md` (see "Morning Handoff") with the run id, the sentinel PID and the time of the fresh pull.

---

## Core System Invariants & Safety Guardrails

1. **Strictly Sequential Execution (`concurrency=1`)**:
   - Single browser worker slot (`worker_slot0`) to avoid bot-flagging and resource contention.
   - Pacing delays between submissions (70s–180s) must be respected.
2. **Per-Company Quota Enforcement (`companyCapHoldUntil`)**:
   - Strictly enforced company limits: **5 applications/day, 10/week, 20/month**.
   - Held jobs have `companyCapHoldUntil` in future; runner automatically skips them until the hold expires.
   - Never bypass or reset company holds for high-volume companies (Google, Amazon, Apple, Microsoft, Capital One, etc.).
   - **10-minute gap per company** (`company_cap.COMPANY_COOLDOWN`): the runner never starts an application at a company within 10 minutes of the last attempt there (sent or staged, keyed on `applicationStartedAt`). It claims the next job in queue order instead, and waits only when every ready job is cooling. Manual Apply clicks are exempt. Seeing one company's postings interleaved with others is expected, not a ranking bug.
3. **No Hallucinated Answers / Essays**:
   - If a job form requires subjective candidate essays (e.g. "Describe an architectural migration you led", "Why our company?"), it **must** remain in `NEEDS_REVIEW`.
   - Never fabricate candidate preferences (e.g. travel willingness, specific team choices, unlisted GPA).
4. **No Bot-Wall / Captcha Bypassing**:
   - Cloudflare, Turnstile, hCaptcha, or reCAPTCHA blocks must be classified as `MANUAL_REVIEW` (`BOT_PROTECTED_BOARD`).
   - Never attempt to automate captcha solving; candidate completes these by hand.
5. **Browse Jobs Exclusion**:
   - All queued, applying, and processed jobs must be excluded from Browse Jobs (`/jobs/discover`) and sidebar job counters using composite keys, normalized company/title, and application URLs.
6. **Queue Watermarks**:
   - Controlled via `apps/api/app/services/intelligence/night_batch_config.py`:
     - `LOW_QUEUE_WATERMARK = 2000`
     - `HIGH_QUEUE_WATERMARK = 5000`

---

## Fresh-Jobs-First Intake (last 24 hours)

Postings published in the **last 24 hours** are pulled and applied to before anything already waiting in the queue. Run this at the start of every night loop, and again whenever the last fresh pull is more than ~3 hours old (check it on every tick). The runner's own 14-day scrape also covers the last 24 hours, so it counts as a fresh pull. When the run is starved (see "When the submittable boards run dry"), pull on every tick.

### Step 1: Pull the last 24 hours of postings
Run this **before** `POST /application-assistant/autopilot/start`. Starting the runner also starts the queue preprocessor, which immediately launches its own 14-day (`hours=336`) scrape, and only one scrape can run at a time.
```bash
curl -s -X POST http://127.0.0.1:4000/jobs/discover/scrape \
  -H "Content-Type: application/json" \
  -d '{"hours": 24, "roles": "swe", "mode": "ats"}'
```
- `409 Scrape already running`: wait for the running scrape to finish (a 14-day scrape also covers the last 24 hours), then re-run the 24-hour pull.
- Poll until `running` is `false` and read `lastResult`:
  ```bash
  curl -s http://127.0.0.1:4000/jobs/discover/status
  ```
- The scrape merges into the existing snapshot; it does not drop older postings.

### Step 2: Get the fresh postings into the queue
The queue preprocessor copies the snapshot into discovered jobs and enqueues eligible ones within one cycle (~30s) once the runner (or `POST /application-assistant/autopilot/queue-preparation/start`) is running. Hard filters, duplicate checks and company blacklist still apply.

Intake is gated by the queue watermarks. Check `GET /application-assistant/autopilot/queue-preparation`:
- `queueReplenishing: true` / `queueAtCapacity: false`: fresh postings are enqueued automatically.
- Paused (QUEUED reached `HIGH_QUEUE_WATERMARK` = 5000 and has not drained to 2000): new postings are **not** enqueued. Either send them through the priority-intake route `POST /api/jobs/import/batch` (bypasses the watermark; requires `CAREEROS_IMPORT_API_TOKEN` in `.env`), or raise `CAREEROS_QUEUE_HIGH_WATERMARK` and restart the API. Never delete queued jobs to make room.

### Step 3: Ordering — fresh jobs go first automatically
No manual reordering is needed. The runner claims jobs by `job_filter_ranker.queue_priority_score`, which is lexicographic:
1. **Recency band**: last 24 hours, then 1–3 days, 3–7 days, 7–14 days, 14–30 days, older/undated.
2. **Role**: Senior → Forward Deployed Engineer → Principal → SDE 2 → Staff → SDE 1 → other qualifying SWE titles (`role_priority_rank`). "Senior Staff" counts as Staff, "Senior Principal" as Principal.
3. **Location** (within a role): Washington State (Seattle, Bellevue, Redmond, Kirkland, Auburn, rest of WA) before the rest of the US. Washington, D.C. is not Washington State.
4. Freshness within the band, then match score.

So every fresh job outranks every older queued job; within a band, a Senior role anywhere in the US beats a Seattle Staff role, and Senior Seattle beats Senior elsewhere. International postings sit below all domestic ones.

When the runner applies to something lower-ranked than expected, the cause is almost always a claim-time filter, not the queue order: company daily/weekly/monthly holds (big Seattle employers hit the 5/day cap early) or the submittable-board preference skipping Workday/aggregator postings. Replay the claim order (sort by `queue_priority_score`, `company_cap.partition_by_cap`, `_is_submittable_board`) before changing the ranking.

- Do **not** push fresh jobs through `priorityJobIds`: the runner treats those as manual Apply clicks, which bypasses the per-company caps and the profile-readiness gate.
- An older job can still run before a fresh one only when:
  - the fresh job's company is on a `companyCapHoldUntil` hold (pacing always wins);
  - `submittableBoardsOnly` is on (the default): fresh jobs go first among Greenhouse/Lever/Ashby boards, and other boards wait until those are exhausted. Start with `"submittableBoardsOnly": false` if freshness must win across every board;
  - the user manually clicked Apply on a specific job;
  - the fresh posting has no parseable posting date (it gets no recency bonus).

### Step 4: Verify fresh jobs are at the head of the queue
```python
import sqlite3, json
from datetime import datetime, timezone, timedelta

conn = sqlite3.connect('apps/api/data/career_os.db')
c = conn.cursor()
c.execute("""
    SELECT payload FROM entities
    WHERE entity_type = 'aa_autopilot_job'
      AND json_extract(payload, '$.status') = 'QUEUED'
""")
now = datetime.now(timezone.utc)
def age_h(d):
    v = d.get('postingDate') or d.get('datePosted')
    try:
        dt = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        return (now - (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))).total_seconds() / 3600
    except Exception:
        return None
jobs = [json.loads(r[0]) for r in c.fetchall()]
fresh = [j for j in jobs if (age_h(j) or 1e9) <= 24]
print(f"QUEUED={len(jobs)} fresh(<24h)={len(fresh)}")
for j in sorted(jobs, key=lambda j: j.get('queuePriority') or 0, reverse=True)[:10]:
    print(f"{j.get('queuePriority'):>9.1f} age={age_h(j) or -1:5.1f}h {j.get('company')} - {j.get('title')}")
```
The top rows should all be under 24h old (unless they are on a company hold). Then confirm the runner's current/next job in `GET /application-assistant/autopilot/status` is a fresh posting.

### When the submittable boards run dry
Submissions come almost entirely from Greenhouse/Lever/Ashby. On a typical night those are used up within the first one or two hours, and the big employers hit their daily caps soon after. From then on the runner keeps processing but nearly nothing reaches submit. On 2026-10-09 the first 90 minutes produced 8 submissions and the next five hours produced 2.

Check this on every tick (run from `apps/api`):
```python
import sqlite3, json
from app.services.application_assistant.autopilot_runner import _is_submittable_board
from app.services.application_assistant.company_cap import partition_by_cap

conn = sqlite3.connect('data/career_os.db')
jobs = [json.loads(r[0]) for r in conn.execute(
    "SELECT payload FROM entities WHERE entity_type = 'aa_autopilot_job'")]
queued = [j for j in jobs if j.get('status') == 'QUEUED']
applyable, held = partition_by_cap(queued, jobs)
print(f"QUEUED={len(queued)} held={len(held)} applyable={len(applyable)} "
      f"submittable={sum(map(_is_submittable_board, applyable))}")
```
The run is **starved** when `submittable` is 0 and no job was submitted in the last two ticks. Then:
1. Run the 24-hour pull on every tick instead of every ~3 hours. Newly published Greenhouse/Lever/Ashby postings are the only new source of submissions.
2. Follow the user's choice from "Before the user leaves": keep the runner triaging the other boards, or stop it until a pull brings submittable jobs (then start it again).
3. Never lift company holds or use `priorityJobIds` to feed it.
4. Record the time the run became starved in the handoff.

---

## The Audit (every tick)

Run this on every tick, covering **every job touched since the previous tick**. A 30-minute tick covers 40–120 jobs, most of them fast `MANUAL_REVIEW` outcomes, so a "last 15 jobs" query misses most of them. Also re-run the Fresh-Jobs-First Intake when it is due.

### Step 1: Query Runner Status
```bash
curl -s http://127.0.0.1:4000/application-assistant/autopilot/status
```
The status endpoint serves a stale-while-revalidate cache (~3s TTL), so the first poll after a gap returns an old snapshot. Poll twice, or read the run directly (`entity_type = 'aa_autopilot_run'`: `status`, `processedCount`, `submittedCount`, `lastHeartbeatAt`) before deciding the runner is stuck.

Verify:
- `workers[0].status`: `applying`, `filling`, or `idle`.
- Heartbeat is fresh (< 60s old).
- Current job ID, company, title, and step (`recentLogs[-1].message`).

### Step 2: Audit Recent Job Outcomes
List every job touched since the previous tick (pass its UTC time, e.g. `2026-10-09T14:26:00`):
```python
import sqlite3, json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # titles contain zero-width characters

since = sys.argv[1]
conn = sqlite3.connect('apps/api/data/career_os.db')
rows = conn.execute("""
    SELECT payload FROM entities
    WHERE entity_type = 'aa_autopilot_job'
      AND json_extract(payload, '$.updatedAt') >= ?
      AND json_extract(payload, '$.status') != 'QUEUED'
    ORDER BY json_extract(payload, '$.updatedAt')
""", (since,)).fetchall()
print(f"touched since {since}: {len(rows)}")
for (payload,) in rows:
    d = json.loads(payload)
    print(f"[{d.get('status')}] {d.get('company')} - {d.get('title')} ({d.get('id')})")
    if d.get('status') not in ('SUBMITTED', 'SKIPPED'):
        print(f"  lastError: {(d.get('lastError') or '')[:300]}")
        print(f"  pending: {[q.get('question') if isinstance(q, dict) else q for q in d.get('pendingQuestions') or []]}")
```
Most `MANUAL_REVIEW` rows are correct and need no action: Workday candidate-account sign-in, "no application form on the posting page", account-password pages, and bot walls. Skim them by reason. Spend the tick on `SUBMITTED`, `NEEDS_REVIEW` and `SUBMISSION_UNKNOWN`.

### Step 2b: Verify answers match the profile
Answers must come from the `profile` key in `kv_store` (the `user_profile`, `user_profile_default` and `candidate_profile` keys are stale copies nothing reads). For the jobs just processed, compare the `answers` on each `aa_autopilot_job` against the profile. This prints the answers that matter for every submission since the previous tick:
```python
import sqlite3, json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

since = sys.argv[1]
WORDS = ('sponsor', 'authoriz', 'city', 'locat', 'reloc', 'resid', 'live', 'visa', 'name')
conn = sqlite3.connect('apps/api/data/career_os.db')
for (payload,) in conn.execute("""
    SELECT payload FROM entities
    WHERE entity_type = 'aa_autopilot_job'
      AND json_extract(payload, '$.status') IN ('SUBMITTED', 'SUBMISSION_UNKNOWN')
      AND json_extract(payload, '$.updatedAt') >= ?
""", (since,)):
    d = json.loads(payload)
    print(f"[{d.get('status')}] {d.get('company')} - {d.get('title')}")
    for k, v in (d.get('answers') or {}).items():
        if any(w in k.lower() for w in WORDS) or str(v).lower() == 'checked':
            print(f"    {k[:100]!r} -> {str(v)[:70]!r}")
```
Check:
- Sponsorship questions must match `workAuth.requiresSponsorshipNowOrFuture` (currently **Yes**, H-1B); work-authorization questions must match `workAuth.authorizedToWorkInUS`. Exception: "authorized to work … for any employer … without restriction" (or "permanent basis") is correctly answered **No**, because H-1B is tied to the sponsoring employer. The stored `answers` keys are cut to 50 characters, so read the full question from the job's `aa_form_field` entity (`fullQuestionText`) before calling a mismatch.
- City/location answers must match `city`/`state` (currently Auburn, Washington), never another city.
- Name fields must hold the candidate's name. The form filler has typed other answers (a degree, a phone number) into First Name; DOM verification has caught every case so far, but a submitted one is a stop-the-run defect.
- Residence/on-site questions must never claim the candidate already lives somewhere they don't; with `relocate: Yes` the answer is "willing to relocate".
- `answers` entries whose value is `checked` and whose key is an option label ("No, I do not require sponsorship ...", "Yes, I am on an F1 Visa ...") mean healing ticked a box of a choice group. Open the `_presubmit.png` screenshot (crop and enlarge it; Greenhouse draws a ticked box as a grey check, an unticked one as an empty square) and confirm only one option per single-choice question is ticked.

A mismatch is a stop-the-run defect: `POST /application-assistant/autopilot/stop`, reproduce with `profile_answer_resolver.resolve_answer(question, profile, options)`, fix, add a regression test (Step 4), deploy and restart (see "Deploying a Fix Mid-Run").

### Step 3: Triage & Classify
- **`MANUAL_REVIEW`**:
  - Check if reason is `BOT_PROTECTED_BOARD`, hCaptcha, reCAPTCHA, or unsupported portal.
  - If valid bot wall, confirm classification is correct and leave in `MANUAL_REVIEW`.
- **`NEEDS_REVIEW`**:
  - Inspect `unresolvedFields` and `pendingQuestions`.
  - Determine if the question is **Deterministic** vs **Subjective**:
    - **Deterministic**: Standard EEOC, referral "N/A" phrasing, company employment history ("Are you currently employed here?"), accuracy acknowledgments, payroll states, visa sponsorship.
      -> Proceed to Step 4.
    - **Subjective**: Free-text essays, personal opinions, unrecorded profile details, mandatory cover letter missing.
      -> Leave in `NEEDS_REVIEW`.
    - **Fill bug (resolver right, form filler wrong)**: the most common `NEEDS_REVIEW` cause that is not a personal fact. Signs: `lastError` says "Required field '…' is empty in the live browser DOM", "Could not heal", "Live DOM value '…' doesn't match", or a Phenom page "would not advance". Test it: run `resolve_answer(label, profile, options)` on the blocking label (options from the `aa_form_field` entity's `fullQuestionText` → `options`). If it returns the right answer, the fault is in the Playwright filler. Leave the job, add it to the handoff's daytime list with the board and field, and move on. Filler fixes need a live browser and should not be made overnight.
      -> Leave in `NEEDS_REVIEW`.

### Step 4: Deterministic Fix & Reprocess Workflow
When a deterministic question was missed:
1. Reproduce with `profile_answer_resolver.resolve_answer(question, profile, options)` and find which stage is wrong:
   - **Wrong or missing question type** → `apps/api/app/services/application_assistant/question_classifier.py` (add a pattern to the right `QuestionType` rule).
   - **Right type, wrong answer** → `apps/api/app/services/application_assistant/profile_answer_resolver.py`. Typical cases: a saved or approved answer that matches none of the dropdown options, location pick-lists, visa-type phrasing, or years-of-experience parsing.
2. Write the regression test first in `apps/api/tests/test_question_classifier_regressions.py`, using the exact question text and options from the form, and watch it fail.
3. Fix, then run the focused tests: every test file that touches the classifier or resolver. Never run the full API suite while the dev backend is live (shared SQLite; see `dev-server-restart`).
   ```powershell
   cd apps/api
   pytest -q (rg -l "profile_answer_resolver|question_classifier|resolve_answer|classify_question" tests)
   ```
4. Commit, then deploy with "Deploying a Fix Mid-Run" below. The API runs without `--reload`, so nothing changes until it restarts.
5. Reprocess the job via the API:
   ```bash
   curl -X POST http://127.0.0.1:4000/application-assistant/autopilot/jobs/{job_id}/reprocess
   ```
   Confirm status transitions back to `QUEUED`, and on a later tick confirm the job was submitted with the fixed answer.

### Step 4b: Unblock review jobs with the user's answers
`GET /application-assistant/autopilot/readiness` groups every open question in `NEEDS_REVIEW`/`MANUAL_REVIEW` jobs by how many applications it holds (`jobCount`) and how many it finishes alone (`unblocksAlone`).
1. Answer straight from the profile anything it already covers (address, county, school/degree, time zone, location, work authorization, start timeline).
2. Collect the questions only the user can answer (experience yes/no, relationships at the company, relocation/onsite/travel/contract preferences, personal choices) and ask them with `AskQuestion`, highest `unblocksAlone` first. Dropdown options are often missing from the group; recover them from the `aa_form_field` entities (`fullQuestionText` → `options`) so the answer matches an option exactly.
3. Essays ("Why <company>?", "Describe a time…") must come from the user in their own words. Never write them.
4. Never answer anti-automation checks (e.g. "solve for X to prevent automated applications") or captchas; those stay manual.
5. Submit each answer with `POST /application-assistant/autopilot/question-groups/answer` (`question`, `answer`, `variants`, `jobIds` from the group). It saves the answer to `profile.screeningAnswers` (reused on future forms) and requeues only jobs with nothing left pending.
6. **Never save a company-specific answer this way.** Saved answers carry no company scope, so the resolver reuses them on every employer. "How did you hear about this job?" → "Zscaler Careers Page" was saved this way and got filled into Coinbase and Counterpart Health forms. If an answer names one company (or only makes sense for one), fill that job by hand in Review instead. Save only answers that hold for every employer (e.g. "Company careers page").
7. `/readiness` only lists questions the resolver recorded as pending. Jobs staged by a **DOM verification mismatch** (`lastError` contains "Required field '…' is empty") never show up there and are not requeued when you answer. To find them, extract the field labels from `lastError` and run `resolve_answer(label, profile, options, answer_lib)`. If every blocker now resolves, and the answer source is the profile, the candidate manifest, or a user-approved answer, requeue the job. Leave alone jobs blocked by validation errors, cover letters, contradictions or checkbox-group labels (form bugs).

If the user is not around (overnight), keep the list and ask when they are back. Do not guess answers.

### Step 5: Verify Company Pacing Quotas
Check the active holds:
```python
import sqlite3, json

conn = sqlite3.connect('apps/api/data/career_os.db')
c = conn.cursor()
c.execute("""
    SELECT json_extract(payload, '$.company'), COUNT(*), MAX(json_extract(payload, '$.companyCapHoldUntil'))
    FROM entities 
    WHERE entity_type = 'aa_autopilot_job' 
      AND json_extract(payload, '$.companyCapHoldUntil') > strftime('%Y-%m-%dT%H:%M:%S', 'now')
    GROUP BY json_extract(payload, '$.company')
    ORDER BY COUNT(*) DESC LIMIT 10
""")
for r in c.fetchall():
    print(f"{r[0]}: {r[1]} jobs held until {r[2]}")
```
Ensure major companies remain protected. Company names are not merged across spellings ("Amazon", "Amazon.Com", "Amazon Web Services" each have their own row), so read the list by employer, not by row.

### Step 6: Verify Browse Jobs Count Alignment
Run once at loop start, not every tick. Confirm `/jobs/discover` and sidebar counts do not include queued roles:
```bash
curl -s http://127.0.0.1:4000/jobs/discover/stats
```
Ensure `totalJobs` matches unqueued discoverable roles and does not double-count queued items.

---

## Health Recovery & Troubleshooting

### Stale Heartbeat / Orphaned Worker
If `lastHeartbeatAt` > 60s or worker is frozen:
1. Do **not** blindly wipe the database.
2. Trigger the recovery mechanism by posting to `/application-assistant/autopilot/start` with:
   `{"targetProcessCount": 25, "concurrency": 1, "selfHealing": false}`
3. Verify heartbeat refreshes and worker resumes.

### Deploying a Fix Mid-Run
The API runs **without `--reload`**: a committed fix does nothing until the API restarts, and restarting kills any application in flight.

1. **Stop the runner between applications.** `POST /application-assistant/autopilot/stop` waits 15s for the worker, then cancels it, so stop only when the last `recentLogs` message from `/autopilot/status` is one of these: `Pacing … waiting`, `waiting until`, `Finished:`, `Navigating to … job URL`, or when `workers[0].status` is `idle`. On a starved run nothing reaches submit, so pacing waits never appear; `Navigating to … job URL` is then the usual window. Poll for it:
   ```powershell
   for ($i = 0; $i -lt 120; $i++) {
     $s = Invoke-RestMethod http://127.0.0.1:4000/application-assistant/autopilot/status
     $last = ($s.recentLogs | Select-Object -Last 1).message
     if ($last -match "Navigating to .* job URL|Pacing .*waiting|waiting until|Finished:" -or $s.workers[0].status -eq 'idle') {
       Invoke-RestMethod -Method Post http://127.0.0.1:4000/application-assistant/autopilot/stop; break
     }
     Start-Sleep -Seconds 2
   }
   ```
2. **Restart detached, with a unique log file.** A shell from an earlier restart can keep `careeros-restart.log` open; the next restart then fails without any message and the old code keeps serving. Launch it hidden and log to a new file:
   ```powershell
   $log = "$env:TEMP\careeros-restart-$(Get-Date -Format yyyyMMdd-HHmmss).log"
   Start-Process -WindowStyle Hidden powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -Command `"& '.\scripts\restart-dev.ps1' -Background -SkipOllamaCheck *> '$log'`""
   ```
   It takes ~90s to print `Ready`.
3. **Prove the new code is live** (see `dev-server-restart`): exactly one live process listening on `:4000`, and its start time is later than the commit. A health check alone proves nothing.
4. **Start the runner again** with `{"targetProcessCount": 100, "concurrency": 1}`. Jobs left in `APPLYING` by the stop are recovered to `QUEUED` on start.
5. Reprocess the jobs the fix unblocks (Step 4), and record the commit, deploy time and API PID in the handoff.

---

## Morning Handoff

The night's real output is the handoff, not the chat. Keep **one entry per night** in `NIGHT_BATCH_DECISIONS.md` (`## <date> (night) — …`) and update it in place on each tick rather than appending a section per tick. Keep it in this shape so the user can act on it straight away:

1. **Headline**: hours run, processed, submitted, and when the run became starved.
2. **Submissions**: company and title, with the profile-check result (sponsorship, authorization, location, name).
3. **Check by hand**: `SUBMISSION_UNKNOWN` jobs; the user must look in their email or on the portal.
4. **Questions only the user can answer**, grouped by company, highest `unblocksAlone` first. Include personal facts (relatives at the company, non-competes, licences, travel), consents, and essays (listed, never written).
5. **Fixes made**: commit, what it changes, deploy time, and the job that proved it live.
6. **Daytime bugs**: fill bugs (board, field, example job id), FAILED jobs with an empty `lastError`, duplicate queue rows for one posting. Put anything that could submit a wrong answer first.
7. **Decisions for the user**, e.g. turning `submittableBoardsOnly` off, or allowing a guarded answer.

When the user breaks the loop, give them items 1–4 and 7 in chat and point to the entry for the rest.
