---
name: autopilot-night-batch-loop
description: Autonomous overnight batch application monitoring, 10-application audit loop, deterministic question resolution, and company cap preservation for CareerOS.
---

# Autopilot Night Batch Loop Skill

Autonomous, unattended or monitored overnight batch application processing for CareerOS with continuous safety validation, 10-application audit intervals, deterministic question classification, and strict per-company pacing.

## When to Use

Trigger this skill when:
- The user requests to "run night job", "continue with the night loop", or "monitor overnight batch".
- The user requests an autonomous run with failure/review checking every ~10 applications.
- Reviewing `NEEDS_REVIEW` and `MANUAL_REVIEW` classifications to fix deterministic questions.
- Verifying company quotas (company cap pacing) and Browse Jobs exclusion during batch runs.

---

## Core System Invariants & Safety Guardrails

1. **Strictly Sequential Execution (`concurrency=1`)**:
   - Single browser worker slot (`worker_slot0`) to avoid bot-flagging and resource contention.
   - Pacing delays between submissions (70s–180s) must be respected.
2. **Per-Company Quota Enforcement (`companyCapHoldUntil`)**:
   - Strictly enforced company limits: **5 applications/day, 10/week, 20/month**.
   - Held jobs have `companyCapHoldUntil` in future; runner automatically skips them until the hold expires.
   - Never bypass or reset company holds for high-volume companies (Google, Amazon, Apple, Microsoft, Capital One, etc.).
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

## The 10-Application Audit Cadence

Every **10 applications processed** by the runner, execute the following audit routine:

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
