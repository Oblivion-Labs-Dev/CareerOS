# CareerOS production-readiness plan

Written against the code, not impressions. Every claim below has a file and a
line behind it. Ordered by what actually hurts you, not by what is easiest.

The honest summary: **the Autopilot engine is the mature part of this codebase**
— the answer resolver, the submission guards, the evidence trail and the
duplicate defences are careful, heavily commented, and well tested. What is
threadbare is everything *around* it: authentication, onboarding, the profile
pipeline, and the rendering layer. That is a good position to be in, because the
hard half is done.

---

## 0. What "built on the fly" actually means here

Three concrete signatures, all verifiable:

1. **`parse_resume_fields` is a 25-line regex stub** (`services/resume_parser.py:29`).
   It extracts four things: email, phone, years-of-experience, and **the first
   line of the document as your name**. No education, no employment history, no
   dates, no skills.
2. **Auth guards 2 of ~15 route prefixes**, and says so in its own docstring
   (`middleware/auth.py:11` — *"KNOWN LIMITATION, deliberate for now"*).
3. **30 of 34 pages are `"use client"`** with 2 loading boundaries in the entire
   app, so almost nothing is server-rendered and almost nothing streams.

Everything below follows from those three.

---

## Phase 1 — Correctness and trust (do these first)

### 1.1 Real authentication

**Today:** `AuthGateMiddleware` enforces only `/application-assistant/` and
`/diagnostic/`. The other ~13 prefixes — profile, job discovery, settings,
email, analytics, resume intelligence, story map — are **completely
unauthenticated**. The reason is in the code: 21 frontend files call the API
cross-origin through `getClientApiBaseUrl()`, where the session cookie does not
travel; only 14 go through the same-origin `/api/backend` proxy. Enforcing
broadly today would 401 most of the dashboard.

So the "login" is a Next.js page redirect. Anyone on your network can read your
profile, résumé and application history from port 4000 directly.

**Plan**
1. Migrate the 21 direct callers onto the `/api/backend` proxy. This is
   mechanical — `lib/api.ts` already has both paths, and
   `application-assistant-api.ts` is the worked example.
2. Then flip `_ENFORCED_PREFIXES` to deny-by-default with an explicit allowlist
   (`/auth/`, `/health`, `/static/`).
3. Add one integration test per router asserting 401 without a cookie. This is
   the test that stops the limitation quietly returning.

**Sequencing matters:** step 2 before step 1 breaks the dashboard. Do not
reorder.

### 1.2 Ask for missing answers *before* applying, not after

**Today: no completeness check exists anywhere.** I grepped for one. The system
discovers a missing answer *mid-application*, abandons the attempt, and files the
job in `NEEDS_REVIEW`. That is why **872 jobs** sit there — each one a wasted
browser run.

This is your "it should ask me before doing any applications", and it is the
highest-leverage item in this document.

**Plan**
1. `profile_readiness.py` — a pure function over the profile returning
   `(blocking_gaps, soft_gaps)`. The knowledge already exists and is scattered
   across the resolvers; this centralises it.
2. Run it in two places:
   * **Before a run starts** — the Start button refuses and names what is
     missing, with a link to the field.
   * **Per job, before the browser opens** — using that posting's known question
     set where we have one.
3. A **pre-flight checklist UI** on the Autopilot page: "3 answers needed before
   this run can start", each row deep-linking to the profile field.
4. Feed it from the live data: the 484 jobs currently blocked on an unanswerable
   field are the exact backlog this should surface.

**Payoff:** converts a 40-minute failed batch into a 2-minute form.

### 1.3 Résumé upload that actually fills the profile

**Today:** the parser takes the first line of the PDF as your name and finds an
email with a regex. It is why your profile had no bachelor's, no education
dates, and no employment dates — I added those by hand tonight.

**Plan**
1. Parse **structure**, not just patterns: section detection (Experience /
   Education / Skills), then per-entry company, title, start, end.
   `resume_intelligence/baseline_document.py` already does positioned text-run
   extraction over the approved PDF — reuse it rather than writing a second
   parser.
2. **Never overwrite silently.** Show a diff — "found 4 employers, 2 degrees" —
   and let the user accept per field. Extraction is a suggestion; the profile is
   the record of truth.
3. Round-trip test against the user's own résumé, asserting the fields that were
   missing tonight are recovered.

---

## Phase 2 — The experience feeling premium

### 2.1 Response time

**Today:** 30 of 34 pages are client components. Each mounts, *then* fetches,
often several endpoints in sequence. Two `loading.tsx` files exist in the whole
app, so the rest show blank panels while they wait.

The backend is not the problem — `read_cache.py` already serves dashboard
aggregates stale-while-revalidate in milliseconds. The latency is architectural,
on the client.

**Plan**
1. Convert read-mostly pages (Dashboard, Applications, Jobs, Analytics) to
   **server components** that fetch on the server and stream.
2. Add `loading.tsx` per route with **content-shaped skeletons**, not spinners.
3. Kill the waterfalls: parallel fetches, and `Promise.all` where a page needs
   several endpoints.
4. Measure before and after — Lighthouse and a real navigation trace. Do not
   guess at wins.

### 2.2 Visual quality

**Today:** three competing styling systems — a 552-line `design-language.css`,
per-component CSS modules, and heavy inline `style={{...}}` (the profile form I
edited tonight is almost entirely inline). Inline styles cannot express hover,
focus, media queries or dark mode, which is why polish is uneven.

**Plan**
1. **One system.** Tokens in `design-language.css`, everything else in CSS
   modules. Inline styles only for genuinely dynamic values.
2. Build the missing primitives — `Field`, `FormRow`, `Panel`, `EmptyState`,
   `Skeleton` — in `@career-os/ui`, then adopt page by page.
3. Fix state coverage: every interactive surface needs hover / focus-visible /
   disabled / loading / empty / error. Most today have default and hover only.
4. Audit dark mode and reduced motion, which the repo's own guidance requires.

**Do this after 2.1.** A fast ugly page can be restyled; a beautiful slow one
still feels cheap.

### 2.3 Information architecture

**Today:** 34 routes, several overlapping — `/applications`,
`/application-assistant`, `/apply-pilot`, `/autofill`, plus `/jobs`,
`/jobs/discover`, `/jobs/target-companies`, `/job-search-portals`. Your standing
rule is one implementation per capability; the route list has drifted from it.

**Plan**
1. Inventory every route: live, dead, or duplicate. Expect to delete several.
2. Collapse to a task-shaped spine: **Profile → Find work → Apply → Track**.
3. Make Autopilot a control centre, not a second dashboard — consistent with the
   separation you already set.

---

## Phase 3 — Keeping it production-grade

1. **Fix the 13 pre-existing test failures.** They have been red long enough to
   become background noise, which is exactly when a real regression hides among
   them. One is a time bomb (`test_lever_adapter`'s hardcoded fixture date) that
   will now fail every single day.
2. **CI that gates.** `scripts/ci-run.mjs` exists; make it required, and make
   Python typing non-advisory once the backlog is clear.
3. **Error boundaries and real empty states.** 2 across 34 routes today.
4. **Structured operational logging** for the submission path specifically —
   you debug live runs by reading `api.log`, so it should be queryable.

---

## What I would do first, if you only did one thing

**Phase 1.2 — the pre-flight answer check.** It directly answers what you asked
for, it converts 872 stalled jobs into a short worklist, and it stops wasting
real browser runs on applications that were never completable. It is also
self-contained: one new module, one gate, one UI panel, no migration risk.

Then **1.1 (auth)**, because it is a genuine exposure and the migration is
mechanical, and then **1.3 (résumé parsing)**, because it removes the manual
data entry that both of us have been doing by hand.

Phase 2 is where the product starts to *feel* premium — but doing it before
Phase 1 would be polishing a system that still silently fails mid-application.

---

## Estimating honestly

I have not put day counts on these. The two that are genuinely well-understood
and low-risk are **1.2** and **1.1**. **1.3** depends on how varied the résumés
are. **2.1** and **2.2** are open-ended by nature — they should be done
incrementally, page by page, with a measurement after each, rather than as one
rewrite. Avoiding a big-bang rewrite is the single most important constraint
here: the Autopilot engine is good, and most of the risk in this plan comes from
disturbing it.
