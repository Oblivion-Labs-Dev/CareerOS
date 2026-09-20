# CareerOS Agent Guide

## 🔄 1. Development Lifecycle

Every task follows this lifecycle:

### 🔍 A. Understand

1. Read the task, acceptance criteria, and `agent/ARCHITECTURE.md`.
2. Inspect the working tree before editing.
3. Inspect only the code and tests relevant to the task.
4. Trace the affected flow and identify the likely change point.
5. State a short implementation plan before editing.

### ⚠️ B. Surface Design Decisions

Do not silently make meaningful architectural or product decisions.

If implementation requires a meaningful decision, stop before implementing and report:

### ⚠️ DECISION NEEDED

**Question**
Clearly state what needs to be decided.

**Option A**
Describe the option.

✅ Pros:

* ...

❌ Cons:

* ...

**Option B**
Describe the option.

✅ Pros:

* ...

❌ Cons:

* ...

### ⭐ RECOMMENDATION

Recommend one option and briefly explain why.

### ⏸️ WAITING FOR APPROVAL

Do not implement the decision until approval is given.

Do not interrupt for trivial implementation details that already follow established repository patterns.

Examples of decisions that should be surfaced:

* Significant data-model changes
* New architectural layers
* Major dependency additions
* REST/API contract changes with multiple reasonable designs
* Synchronous vs. asynchronous processing
* Caching strategy
* Authentication or authorization changes
* Consistency-model changes
* Background processing
* Significant frontend state-management changes

### 🛠️ C. Implement

1. Make the smallest reasonable change.
2. Preserve existing behavior unless the task explicitly changes it.
3. Avoid unrelated refactors or rewrites.
4. Follow existing project patterns and abstractions.

### 🧪 D. Verify

1. Verify every acceptance criterion.
2. Run focused tests first; run broader tests when warranted.
3. For bugs, add a regression test when practical.
4. Do not weaken safeguards or validation just to make tests pass.

### 🔎 E. Review

Before declaring the task complete:

1. Review the final diff.
2. Remove unnecessary or unrelated changes.
3. Check edge cases and failure paths.
4. Check for duplicated logic or unnecessary complexity.
5. Confirm system invariants remain intact.
6. Fix issues found and rerun affected tests.

### 🏁 F. Finish

1. Update `agent/ARCHITECTURE.md` only if architecture actually changed.
2. Report what changed.
3. Report exactly what was verified.
4. Report remaining risks or unresolved issues.

📌 **Code is the source of truth.** If documentation conflicts with the implementation, verify the implementation and correct stale documentation.

---

## ✅ 2. Definition of Done

A task is complete only when:

* ✅ Acceptance criteria are satisfied.
* 🧪 Relevant tests pass.
* 🛡️ Changed behavior has regression coverage when practical.
* 🔎 The final diff has been reviewed.
* 🔒 Existing safety and system invariants remain intact.
* 📋 Verification evidence is reported.

🚫 Never mark a task complete solely because code was written or a command succeeded.

---

## 🏗️ 3. Architecture Maintenance

Update `agent/ARCHITECTURE.md` only when a change affects:

* 🧩 Component responsibilities
* 🔄 Important data or control flows
* 📦 Key module ownership
* 🔗 Major dependencies
* 🛡️ System invariants
* 🧪 Testing architecture

Do not update it for ordinary implementation changes, bug fixes, refactors, or UI changes that do not alter architecture.

Keep architecture documentation concise and verify it against the actual code.

---

## 🗂️ 4. Repository Guide

### 🚀 Start Here

* 🖥️ Dashboard: `apps/web` (Next.js), port 5000.
* ⚙️ API: `apps/api` (FastAPI), port 4000.
* 🐍 Use the existing API virtual environment: `apps/api/.venv/Scripts/python.exe`.
* 🏗️ Wider system architecture: `docs/architecture.md`.
* 📦 Arsenal is a sibling repository; keep career logic in CareerOS.
* ⚠️ Local diagnostic scripts and application evidence may be untracked user work. Never overwrite or delete them without understanding them first.

### 🔄 Application Flow

* 🖥️ UI: `apps/web/components/application-assistant/autopilot/`
* 📋 Job types/display helpers: `job-types.ts`, `job-presentation.ts`
* 🔌 Single Apply endpoint: `apps/api/app/routers/application_assistant/tailoring_receipts.py`
* ⏱️ Scheduling/job lifecycle: `apps/api/app/services/application_assistant/autopilot_runner.py`
* 🌐 Browser interaction: `playwright_autopilot_executor.py`
* 📄 Resume drafting/rendering: `resume_diff_service.py`
* 🤖 Model diagnosis validation: `healing_response.py`

### 🤖 AI Behavior

When changing prompts, models, model-driven decisions, or AI validation:

1. 🎯 Identify the AI behavior that could regress.
2. 🧪 Add or update an eval case when appropriate.
3. 🔎 Verify grounding, ambiguity handling, and safety constraints.
4. 🚫 Never treat model output alone as proof of correctness.

---

## 🛡️ 5. Verification & Safety

### 🧪 Testing

* API tests use an isolated temporary database and browser profile through `tests/conftest.py`.

Focused regression tests:

* 🧪 `test_autopilot_run_handoff.py`
* 🧪 `test_autopilot_tailoring_mode.py`
* 🧪 `test_healing_response.py`

From `apps/web`, typecheck with:

`node ../../node_modules/typescript/bin/tsc --noEmit`

if the package-manager executable shim is unavailable.

### 🐛 Regression Rule

For every reproducible bug:

1. 🔴 Reproduce the failure.
2. 🧪 Add a regression test that fails because of the bug.
3. 🔧 Fix the root cause, not only the observed symptom.
4. 🟢 Confirm the regression test passes.
5. 🛡️ Keep the test as permanent protection.

If a regression test is not practical, document why and provide another repeatable verification method.

### 🚨 Application Safety

* 🚫 Ordinary UI tests must never submit real applications.
* 🔐 Live application runs require `CAREEROS_LIVE_APPLY=1`.
* 🔐 They also require at least ten explicitly approved comma-separated `CAREEROS_APPROVED_JOB_IDS`.
* 🚫 Never add replacement recipients without approval.
* ➡️ Run approved applications sequentially.
* ⚠️ Skipped, expired, review, and failed outcomes never count as submissions.
* 🚫 A changed button or accepted HTTP request is not proof of submission.
* ✅ Require the exact job's terminal state and receipt, then inspect confirmation evidence.
* 🛡️ Preserve selected resume mode, duplicate-submission guards, and human review for unresolved answers.
* 🚫 Never weaken these safeguards merely to make a test pass.

### 🔐 Sensitive Data

Never commit:

* 🔑 Credentials
* 🍪 Browser sessions
* 📄 Private resumes
* 📋 Application logs

---

## 📸 6. Evidence & UI

Local artifacts:

* 📷 `apps/api/data/application_assistant/screenshots/`
* 📄 `apps/api/data/application_assistant/tailored_resumes/`

Additional rules:

* ⚠️ Do not run `next build` against the same `.next` directory while `next dev` is running.
* 🎨 Shared visual rules live in `apps/web/app/design-language.css`.
* 🧩 Component-specific rules belong in CSS modules.
* ♻️ Reuse theme tokens and honor reduced motion.
* 🧹 Prefer extracting cohesive helpers and types over adding responsibilities to already-large modules.
* 🚫 Avoid unrelated rewrites while debugging live runs.

---

## 📊 7. Required Task Completion Report

After **every implementation change**, report results using this structure.

### ✅ WHAT WORKED

* What was successfully implemented.
* Which acceptance criteria are satisfied.
* Important behavior that now works.

### 🧪 VERIFIED

Report exactly what was actually executed:

* Tests run
* Type checks
* Builds
* Manual verification
* Relevant edge cases

🚫 Never claim something was verified if it was not actually run.

### 🚩 NEEDS MY ATTENTION

Highlight anything requiring human review, judgment, or follow-up.

Use:

> 🚩 **IMPORTANT:** ...

for anything particularly important.

If nothing requires attention:

> ✅ No critical flags.

### ⚠️ TRADEOFFS / SHORTCUTS

Report:

* Technical shortcuts
* Deferred cleanup
* Temporary implementation choices
* Production considerations

Explain why the tradeoff was made.

### ❌ NOT DONE / FAILED

Explicitly report:

* Failed tests
* Incomplete requirements
* Unverified behavior
* Commands that failed
* Known bugs

🚫 Never hide or minimize failures.

### 💡 DESIGN NOTES

Highlight architectural or implementation decisions worth understanding.

Keep these concise.

### ➡️ NEXT BEST STEP

Recommend exactly **one** next action based on the current repository state.

Do not automatically execute that action unless it is already part of the approved task.

---

## 🤝 8. Human Decision Rule

The agent is an implementation and review assistant.

The human owns product and architectural decisions.

When multiple reasonable approaches exist and the choice has meaningful consequences:

1. 🛑 Stop before implementing.
2. 📋 Present the options.
3. ⚖️ Explain meaningful pros and cons.
4. ⭐ Recommend an option and explain why.
5. ⏸️ Wait for approval.
6. 🛠️ Implement the selected approach.

The agent should still make ordinary low-level implementation decisions independently when they clearly follow existing repository conventions.

The goal is **not** to ask permission constantly.

The goal is to make important decisions **visible and deliberate**.
