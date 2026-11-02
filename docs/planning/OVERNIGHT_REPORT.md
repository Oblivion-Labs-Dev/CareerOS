# Overnight session report — 2026-09-19

Deterministic fixes only. **No application was submitted, no Autopilot run was
started, and no browser was driven against a job board.** All work was code plus
one database requeue, applied only after the full test suite had run.

---

## 1. What was wrong, and what changed

### Cloudflare — a fabricated CAPTCHA verdict (≈67 jobs)

You said there was no CAPTCHA on those postings. You were right.

`playwright_autopilot_executor.py` decided a board was bot-protected by testing
for reCAPTCHA's **presence** in the page HTML:

```js
if (/g-recaptcha|grecaptcha/i.test(html)) return 'reCAPTCHA';
```

Greenhouse embeds reCAPTCHA on every board, so that was true for every
Greenhouse posting, and the caller used it to **overwrite the real failure
reason**. The stored evidence still held the truth:

| | |
|---|---|
| `qwenReview.reason` (real) | `Page contains active validation errors: This field is required.` |
| `lastError` (what you saw) | `reCAPTCHA bot protection … blocked the submission` |

A required field nobody filled is fixable and retryable. A bot wall is neither,
and it classifies as `BOT_PROTECTED_BOARD`. Mislabelling one as the other buried
live postings.

**Fixed:** detection now requires a challenge that is actually *presented* —
a visible element of real size. The reCAPTCHA v3 badge is excluded by name.
Writing the test caught a hole in the first version of my own fix: the badge
wraps a 256×60 `api2/anchor` iframe, nearly the same size as a genuine v2
checkbox, so dimensions cannot separate them — the badge ancestor has to be
excluded in **both** scan loops.

### ServiceNow — a real bot wall, and your premise was inverted

Not ServiceNow-specific, and not fixable:

* **Bosch is equally blocked** (56× DataDome)
* **ServiceNow is the only SmartRecruiters employer that ever submitted** (2 jobs).
  Every other SmartRecruiters company has **zero**.
* DataDome guards `jobs.smartrecruiters.com` too, not just the API host — 34 of
  the blocks are on the correct apply URL, and the URL rewrite (landed 2026-09-06)
  predates the failures (09-13 → 09-17), so it is working.

These 147 jobs are **correctly** in Manual Review. Nothing to fix. The
`oneclick-ui` URL you sent is a different apply flow that might sidestep it —
untested, and I would not promise it.

### Canonical — four distinct blockers, three fixed

| Count | Question | Outcome |
|---|---|---|
| 43 | "I agree to use only my own words… AI content will disqualify" | **Deliberately not auto-answered — see §2** |
| 43 | "How did you perform in mathematics at high school?" | Left unclassified; your profile holds no such fact |
| 42 | "…how many companies have you worked for?" | Fixed — was answered with a *qualification level* |
| 5 | "What time zone are you in?" | Fixed — was answered **"Yes"** |

The employer-count question dates its window by naming a degree, and the bare
`degree` pattern intercepted that incidental mention. The time-zone question was
classified as `TIMEZONE_AVAILABILITY`, whose resolver answers "Yes" — correct
for *"can you work Eastern hours?"*, meaningless here, so the field stayed empty.
It now derives **Pacific Time (PT)** from Auburn, WA.

### Cross-company defects found by surveying all 2,771 review jobs

| Count | Defect | Severity |
|---|---|---|
| 18 | `"Are you authorised to work…"` → classified **`COUNTRY`** | **Correctness-critical** |
| 45 | `"Have you been employed, or otherwise engaged, by…"` and `"Are you presently employed by…"` unmatched | Blocked |
| 16 | `"End date month"` had no classification at all | Blocked |
| 12 | `"personal relationship with a current employee"` unmatched | Blocked |

The work-authorisation one matters most: the patterns were **American-spelling
only** (`authorized`), so the British `authorised` matched nothing and fell to
the bare `COUNTRY` pattern — a yes/no work-authorisation question answered with
a country name. You require sponsorship, so that answer has to be exactly right.
The code comment right above it documents the *same failure* happening
previously for a different reason (an adverb). Both spellings are now accepted,
as is `organisation`.

`End date month` is a plain asymmetry: Greenhouse renders the education block's
month and year as two required selects, only the year half was ever classified,
and `_resolve_education_history` already knew how to produce a month — nothing
ever asked it for one.

---

## 2. One thing I deliberately did **not** do

You asked me to fix the consent checkbox deterministically. I did not, and this
is the one decision in the session worth your review.

The full text reads:

> "During this application process I agree to use only my own words. I understand
> that plagiarism, **the use of AI or other generated content will disqualify my
> application**."

CareerOS drafts answers with a language model. Ticking that box on your behalf
would assert something untrue to the employer and, by Canonical's own terms,
disqualify the application it was trying to complete. That is the same failure
as fuzzy-matching a demographic answer — a false statement of fact to an
employer — which you rejected before.

So it is now **classified and routed to you** with a plain explanation, rather
than answered. Those 43 Canonical jobs are yours to finish by hand, honestly.
If you disagree, the resolver is one function and easy to change.

---

## 3. Jobs moved back to the queue

**365 requeued. Queue: 56 → 421. Needs-review: 1,238 → 872.**

Conservative by design — a job moved only when *every* recorded blocker is now
resolvable:

| Outcome | Jobs |
|---|---|
| Requeued (all fields now answerable) | 154 |
| Requeued (bot-wall label proven fabricated) | 211 |
| Left: permanently blocked | 1,532 |
| Left: still has an unanswerable field | 484 |
| Left: no form / ambiguous match | 220 |
| Left: no required-field failure recorded | 157 |
| Left: **real** bot wall | 13 |

The fabricated-label group was identified from evidence, not assumption: where
`qwenReview.reason` names validation errors rather than a challenge, the
bot-wall verdict came from the buggy detector. Where there is no evidence to
check, the label was **left standing** — wrongly assuming a wall costs one
retry; wrongly assuming none wastes an attempt on a board that will never accept it.

Top companies requeued: Cloudflare 67, Datadog 62, Braze 37, Lyft 15,
Intercom 18, Coinbase 13, Sezzle 13.

---

## 4. What your résumé / profile is missing

Ordered by how many applications it blocked.

### Blocking applications right now

1. **English level — not recorded (25 jobs).** Boards outside the US ask this
   constantly. One profile field clears all of them.
2. **Citizenship / nationality country — not recorded (17 jobs).** Asked as
   "US Export Control laws: in which country did you obtain citizenship,
   nationality, or permanent residency?"
3. **No undergraduate degree recorded (≈42 jobs indirectly).** Your education has
   exactly one entry — the Santa Clara master's. Forms routinely ask for the
   bachelor's, and Canonical's employer-count question is literally phrased
   *"since you graduated your first undergraduate degree"*. That degree is
   missing from the profile entirely.
4. **No `startDate` on the education entry.** Only `06/2019` (end). Any form
   asking for education start month/year cannot be answered.

### Asked often, not recorded

5. **Salary expectation** — not set.
6. **Security clearance** — not set (defence-adjacent boards ask).
7. **Veteran status** and **disability status** — not set. These are standard EEO
   questions; leaving them unset means every such form needs you.
8. **Portfolio / personal website** — not set. LinkedIn and GitHub are.
9. **Time zone** — not set. Now *derived* from Auburn, WA, but an explicit value
   would be more robust if you travel or relocate.

### Worth a look

10. **`race/ethnicity` is recorded as "Asian".** You are South Asian, and you
    previously flagged that matching "Asian" onto a narrower option states a
    false fact. Worth confirming the stored value is what you want submitted.
11. **GPA is 3.34 and is set** — but a code comment in `_resolve_gpa` still says
    the profile has none. Stale comment, harmless, worth correcting.

### Questions no profile field can fix

Canonical asks how you performed in **high-school mathematics** and in your
**native language** (43 each). Riot asks about your **passion for gaming**.
Several boards ask **how AI changed the way you work**. These are essay answers
about you; they need either a recorded answer in your own words or a manual
reply. The biggest single win available is adding a short written answer for the
recurring ones to your answer library.

---

## 5. Tests

| | |
|---|---|
| New tests written | **50** across 5 files |
| Full suite | **1,040 passed, 14 failed** |
| Regressions introduced | **0** |

The 14 failures are the exact baseline set, verified before and after. Thirteen
are pre-existing. The fourteenth, `test_lever_adapter`, **started failing today
for a reason unrelated to any change**: its fixture has a hardcoded epoch
(`2026-08-20`) tested against a *relative* 30-day cutoff, so it aged out when the
date rolled to 2026-09-19. It will now fail every day until the fixture is made
relative. Worth a two-line fix.

New test files:

* `test_bot_challenge_detection.py` — runs real Chromium, because the question
  is one of computed visibility and a string assertion would prove nothing
* `test_canonical_deterministic_answers.py`
* `test_company_cap_pacing.py`
* `test_answer_story_evidence.py`
* `test_submission_idempotency.py`

---

## 6. Also landed earlier in the session

* **Duplicate-application defence.** "Could not prove it submitted" was recorded
  as `FAILED`, which is a retryable bucket — so a possibly-sent application went
  straight back on the queue. Now split: `FAILED` means *proven* not sent;
  anything unproven is `SUBMISSION_UNKNOWN` and is never retried automatically.
  Decided by a durable marker the executor writes immediately **before** clicking
  submit. A confirmation email is later evidence, never a trigger.
* **Company pacing:** at most 20 applications per employer per rolling 30 days,
  held as a countdown on a `QUEUED` job rather than filed `INELIGIBLE`. Best
  matches go first when a window rolls.
* **Experience corpus reaches application answers.** Your 60 recorded stories fed
  résumé tailoring but nothing fed them to the code that answers questions.
  They are now evidence there too, with each story's `doNotClaim` constraints
  carried across as prohibitions.
* **Docker** was containerized, verified against all 14 checks, then stopped and
  removed at your request. Autostart disabled; restore command saved at
  `C:\Users\amsbo\docker-desktop-autostart-backup.txt`.

---

## 6b. Profile facts you supplied (added after the first report)

You gave three facts; all three are now recorded and resolving.

| Fact | Where it went | Now answers |
|---|---|---|
| English level: **Proficient** | `profile.englishLevel` | "What is your English level?" → `Proficient`, or `C2` on CEFR-scale forms |
| Citizenship: **Indian (non-US)** | `profile.citizenshipCountry` | "In which country did you obtain citizenship…?" → `India` |
| **Bachelor's, Computer Science** | second `education` row | "most recent degree" still resolves the master's; row 1 now resolves the bachelor's |

Three code changes went with them, because in each case the field existed but
nothing could reach it:

1. **`_resolve_english_proficiency` hardcoded `"Fluent"`** and read nothing from
   the profile — a claim about you, asserted on your behalf, and wrong: your
   level is *Proficient*. It now reads `englishLevel` and routes to review when
   none is recorded, because a self-assessment belongs to the person being
   assessed.
2. **The export-control resolver only understood the *status* form** ("are you a
   US person?" → "None of the above"). Several boards ask the *value* form —
   "in which country did you obtain citizenship?" — and got a non-answer, the
   same status-versus-value confusion as the time-zone bug. Both shapes now
   work, and the status form still refuses to claim US citizenship.
3. **The Profile page had no way to record any of this.** It exposed a single
   flat school/degree/discipline set, which the `education` array silently
   overrides, so a second degree was simply unrecordable. There is now an
   **Education editor** (add/remove rows, school / degree / field / start / end)
   plus **Citizenship & work eligibility** fields, so you can maintain all of it
   yourself.

Two caveats worth your eye:

* **The bachelor's is recorded as Santa Clara University**, which is what you
  selected — but it is also where you did your master's, and I flagged at the
  time that this looked unlikely. If it was a misclick, fix it in the new
  Education editor.
* **The bachelor's has no start or end date.** I did not guess one. Any form
  asking for undergraduate dates will still stop and ask you.

Requeueing again after these changes moved **0 further jobs**. That is expected,
not a failure: the jobs blocked on English level or export control are also
blocked on something unanswerable (Canonical's high-school questions, the AI
essays, FINRA licences), and the requeue only moves a job when *every* blocker
is resolved. What these facts changed is the **quality** of the answers those
applications will carry, not how many are unblocked.

---

## 7. Open items for you

1. **Decide on the Canonical originality declaration** (§2).
2. **Add the four blocking profile fields** — English level, citizenship country,
   undergraduate degree, education start date. That is the highest-value hour
   you could spend on this.
3. **Fix `test_lever_adapter`'s fixture date** before it becomes noise.
4. The 869 "no application form / wrong URL" jobs are the **largest remaining
   bucket** and were not touched tonight. They look like a URL-resolution
   problem per source, which is probably the next big deterministic win.
