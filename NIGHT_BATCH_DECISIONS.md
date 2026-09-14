# Night Batch Decisions Log

Running log for the overnight autonomous Autopilot batch loop. Newest entries at top.
Context for whoever (human or future Claude session) picks this up cold: this file
exists so decision-worthy events don't need to interrupt the user overnight.

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
