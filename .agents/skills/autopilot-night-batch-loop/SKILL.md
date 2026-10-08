---
name: autopilot-night-batch-loop
description: Autonomous overnight batch application monitoring, fresh-jobs-first intake (postings from the last 24 hours are pulled and applied to before older queued jobs), 10-application audit loop, deterministic question resolution, and company cap preservation for CareerOS.
---

# Autopilot Night Batch Loop Skill

Autonomous, unattended or monitored overnight batch application processing for CareerOS with fresh-jobs-first intake, continuous safety validation, 10-application audit intervals, deterministic question classification, and strict per-company pacing.

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
- **Agent side**: monitoring must survive between chat turns. Arm a recurring wake-up with the `loop` skill (local: a background PowerShell loop printing a sentinel such as `AGENT_LOOP_TICK_nightloop` every ~30 minutes, watched with `notify_on_output`). On every tick run the 10-application audit, the fresh-pull check and the review-question check below. Check the terminals for an existing loop first; never run two.
- **Breaking the loop**: only on an explicit user request. Then kill the sentinel loop's PID, `POST /application-assistant/autopilot/stop`, and confirm both stopped.

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

Postings published in the **last 24 hours** are pulled and applied to before anything already waiting in the queue. Run this at the start of every night loop, and again whenever the last fresh pull is more than ~3 hours old (check it during the 10-application audit).

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

---

## The 10-Application Audit Cadence

Every **10 applications processed** by the runner, execute the following audit routine (and re-run the Fresh-Jobs-First Intake if the last 24-hour pull is more than ~3 hours old):

### Step 1: Query Runner Status
```bash
curl -s http://127.0.0.1:4000/application-assistant/autopilot/status
```
Verify:
- `workers[0].status`: `applying`, `filling`, or `idle`.
- Heartbeat is fresh (< 60s old).
- Current job ID, company, title, and step.

### Step 2: Audit Recent Job Outcomes
Inspect the last 10–15 processed jobs in `career_os.db`:
```python
import sqlite3, json

conn = sqlite3.connect('apps/api/data/career_os.db')
c = conn.cursor()
c.execute("""
    SELECT payload FROM entities 
    WHERE entity_type = 'aa_autopilot_job' 
      AND json_extract(payload, '$.status') IN ('NEEDS_REVIEW', 'MANUAL_REVIEW', 'SUBMITTED', 'FAILED', 'APPLYING')
    ORDER BY json_extract(payload, '$.updatedAt') DESC LIMIT 15
""")
for row in c.fetchall():
    d = json.loads(row[0])
    print(f"[{d.get('status')}] {d.get('company')} - {d.get('title')} ({d.get('id')})")
    print(f"  aiExplanation: {d.get('aiExplanation')}")
    print(f"  unresolvedFields: {d.get('unresolvedFields')}")
```

### Step 2b: Verify answers match the profile
Answers must come from the `profile` key in `kv_store` (the `user_profile`, `user_profile_default` and `candidate_profile` keys are stale copies nothing reads). For the jobs just processed, compare the `answers` on each `aa_autopilot_job` against the profile:
- Sponsorship questions must match `workAuth.requiresSponsorshipNowOrFuture` (currently **Yes**, H-1B); work-authorization questions must match `workAuth.authorizedToWorkInUS`.
- City/location answers must match `city`/`state` (currently Auburn, Washington), never another city.
- Residence/on-site questions must never claim the candidate already lives somewhere they don't; with `relocate: Yes` the answer is "willing to relocate".
- `answers` entries whose value is `checked` and whose key is an option label ("No, I do not require sponsorship ...", "Yes, I am on an F1 Visa ...") mean healing ticked a box of a choice group. Open the `_presubmit.png` screenshot (crop and enlarge it; Greenhouse draws a ticked box as a grey check, an unticked one as an empty square) and confirm only one option per single-choice question is ticked.

A mismatch is a stop-the-run defect: `POST /application-assistant/autopilot/stop`, reproduce with `profile_answer_resolver.resolve_answer(question, profile, options)`, fix, add a regression test, then restart.

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

### Step 4: Deterministic Fix & Reprocess Workflow
When a deterministic question was missed:
1. Locate `question_classifier.py` in `apps/api/app/services/application_assistant/question_classifier.py`.
2. Add regex pattern to the appropriate `QuestionType` or answer mapping.
3. Add a regression test to `apps/api/tests/test_question_classifier_regressions.py`.
4. Run tests:
   ```bash
   pytest tests/test_question_classifier_regressions.py
   ```
5. Reprocess the job via the API:
   ```bash
   curl -X POST http://127.0.0.1:4000/application-assistant/autopilot/jobs/{job_id}/reprocess
   ```
   Confirm status transitions back to `QUEUED`.

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
      AND json_extract(payload, '$.companyCapHoldUntil') IS NOT NULL
    GROUP BY json_extract(payload, '$.company')
    ORDER BY COUNT(*) DESC LIMIT 10
""")
for r in c.fetchall():
    print(f"{r[0]}: {r[1]} jobs held until {r[2]}")
```
Ensure major companies remain protected.

### Step 6: Verify Browse Jobs Count Alignment
Confirm `/jobs/discover` and sidebar counts do not include queued roles:
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

### Dev Server Restart
If code changes require server restart:
1. Follow `dev-server-restart` skill:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restart-dev.ps1 -SkipOllamaCheck
   ```
2. Verify ports 4000 and 5000 are listening without duplicate zombie PIDs.
