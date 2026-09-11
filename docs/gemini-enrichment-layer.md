# Gemini as an optional intelligence layer

CareerOS decides everything it can deterministically. Profile fields are looked
up, postings are scored by code, resumes are assembled from a verified corpus.
That path runs in milliseconds, keeps no model resident, and works with no
network at all.

Gemini sits beside that path and is consulted only where a language model
genuinely knows something the deterministic path does not. One invariant governs
the whole design:

> **Gemini can make CareerOS better when available. Gemini being unavailable can
> never take CareerOS down.**

Nothing in this layer is load-bearing. Every entry point returns an
`available` / `ok` flag, every caller treats "not available" as its normal path,
and no function in the layer raises.

---

## Architecture

```
CareerOS deterministic pipeline
        │
        ├── confident case ───────────────→ continue, no Gemini call
        │
        └── genuinely uncertain case
                    ↓
         central Gemini queue  (one per process)
          concurrency · rate limit · priority · retry
          cache · dedupe · circuit breaker · schema check
                    ↓
            available + within quota?
             ↙                      ↘
           yes                       no
            │                         │
        enrichment            deterministic fallback
            │                         │
            └──────→ CareerOS continues ←┘
```

### The gateway is the only client

`app/services/gemini/gateway.py` holds the single HTTP path to Gemini. Nothing
else in the codebase constructs a Gemini client. That is what makes the limits
real: five services each with their own retry loop is five services racing for
the same quota, which is exactly how a 140-posting benchmark run came to compete
with a live application.

`submit()` never raises. `ok=False` is the ordinary, expected outcome whenever
Gemini is disabled, rate limited, circuit-open, misconfigured, or answered with
something that failed validation.

### Priority

Work is ordered, not merely queued:

| Priority | Task | Waits for the circuit? |
|---|---|---|
| 0 | Application currently being submitted | no |
| 1 | Application question | no |
| 2 | Resume tailoring | no |
| 3 | Ambiguous match | no |
| 4 | Offline benchmark labelling | **yes** |

Only offline labelling may sit through a circuit cooldown, because nothing is
blocked on it. Everything above it fails fast to its deterministic path rather
than making a person wait.

---

## Where Gemini is used

### 1. Application questions — the clearest win

Open-ended prose ("Why are you interested in this role?", "Describe relevant
experience") is the one place a bigger model is plainly better, and it costs no
local RAM.

Gemini enters the existing answer hierarchy as **level 3a**, ahead of the local
model and behind both deterministic levels:

1. deterministic profile lookup
2. approved answer library
3. **3a — Gemini** *(new)*
4. 3b — local model, if it is switched on
5. staged for the user in **Review**

Two guards stand in front of it:

* `question_is_eligible()` refuses every question with a right answer — anything
  with a canonical profile key, anything with fixed options, and every type the
  classifier marks sensitive or factual (name, email, phone, location, work
  authorisation, sponsorship, demographics, clearance, salary, GPA, dates,
  years of experience). These never reach a language model under any
  configuration.
* `grounding.check()` re-reads the answer afterwards and rejects it if it names
  a technology or a figure that is not already in the candidate's own documents.
  A rejected answer is discarded, never repaired.

If Gemini is unavailable and the local model is off, the application is **staged
in Review**. It is never given an invented answer to keep Autopilot moving.

### 2. Resume tailoring

Gemini may re-word bullets that already exist; it may not write new ones. It
receives the same prompt the local model receives, and its output passes through
the same parser, the same echo check, the same length clamp and the same
`_reject_fabrication` guard — a rewrite that invents a figure is discarded
identically whichever model produced it.

A batch that comes back with the wrong number of bullets is treated as no answer
rather than a partial one: silently mapping a short list onto the slots is how
bullet 3's text once ended up in slot 1.

This does not change the standing default that tailoring is **off**. It does
change what "on" costs: tailoring through Gemini uses no local RAM, which was
the reason it was switched off in the first place.

### 3. Ambiguous job matching

Gemini is **not** in the normal matching path. `ambiguity.assess()` runs first —
pure string scanning, no I/O — and flags a posting only when:

* it has no deterministic score at all;
* its score is within 8 points of the auto-apply boundary;
* no role family can be determined from the text;
* two role families are in a near-tie (runner-up within 90% of the leader);
* the posting states an eligibility requirement **ambiguously** — "clearance
  preferred", "ability to obtain", "or equivalent".

A posting shorter than 400 characters is explicitly *not* ambiguous — it is
empty, and asking Gemini to judge boilerplate spends a call to be told what the
length already said.

### The thresholds were measured, not guessed

Run over 400 real postings from the database, the first version of this gate
flagged **65%** of them. That is not a gate. Three things were wrong:

* **The token `itar` had no word boundaries**, so it matched the middle of
  "military" and flagged 95 postings as export-controlled because they described
  a defence customer.
* **A PhD listed as an alternative** ("a bachelor's and 5 years, or a master's
  and 3, or a PhD") was read as a requirement, and a years-of-experience bar
  matched 140 postings because "8+ years" is in nearly every senior posting.
  The years rule was removed outright — it is the one requirement CareerOS *can*
  check itself.
* **A flatly stated requirement is not ambiguous.** The candidate either
  evidences it or does not. Only a *hedged* requirement is a judgement call, and
  the hedge has to be in the same clause: a 220-character window found
  "preferred" or "or equivalent" next to almost everything.

Plus a looser role-family rule: a share threshold on the leader was replaced by
a direct comparison with the runner-up, because with thirteen families a leader
holding 44% of the signal is dominant, not contested.

| Version | Postings flagged (of 400) |
|---|---|
| first attempt | 65% |
| word-boundary and years fixes | 44% |
| clause-scoped hedging | 23.5% |
| near-tie role families | **15%** |

So roughly one application in seven gets a second opinion, and the other six
never touch the network.

The gate is asymmetric by design:

* Gemini **can** divert a posting to Review.
* Gemini **cannot** talk a posting into being applied to — a posting it likes
  simply keeps the deterministic decision it already had.
* A Gemini opinion below 0.6 confidence is ignored entirely.
* Gemini being unavailable produces **Review**, never a failed run.

The Gemini judgement is stored under `geminiMatchGate` on the job row. The
deterministic `matchScore` is never overwritten, so the two can be compared
later instead of one having quietly replaced the other.

### 4. Offline benchmark labelling (MatchLab teacher)

Runs at the lowest priority, may wait out a cooldown, and is cached permanently.
The job title is redacted from the body before the request is built —
`title_redaction.strip_title()` — because bootstrap labels were title-derived
and the winning scorer read titles, so its 0.945 AUC was partly reconstructing
its own labeller.

Labels are stored as `label_source: "gemini_teacher"`. Never "human". Human
labels override automated ones wherever both exist.

`teacher_run.py --uncertain-first` (the default) orders the pool so a capped run
spends its quota on the postings the cheap label sources disagree about, rather
than on postings they already agree on.

---

## Failure behaviour

| Status | Classification | Behaviour | Moves the circuit? |
|---|---|---|---|
| 429 | `RATE_LIMITED` | backoff + jitter, `Retry-After` honoured, retried | yes |
| 500/502/503/504 | `TRANSIENT` | backoff + jitter, retried | yes |
| 404 | `CONFIG_ERROR` | **no retry**, opens the circuit immediately for the longest cooldown | yes |
| other 4xx | `PERMANENT` | fails fast, reason logged | no |
| timeout / connection | `TIMEOUT` | retried | yes |
| bad JSON or schema violation | `MALFORMED` | one retry, then fallback | **no** |

The 404 rule is the one that matters most in practice: a wrong model name is a
configuration fault, and retrying it on a timer is how a typo becomes a retry
storm against a URL that will never work.

A malformed reply deliberately does not move the circuit. Gemini answering badly
is the opposite of Gemini being down.

### Circuit breaker

Four consecutive availability failures open the circuit for 5 minutes (doubling
to a 15-minute cap on each failed probe). After the cooldown it goes half-open
and lets exactly one probe through; success closes it, failure reopens it for
longer.

State is mirrored to `data/gemini/circuit.json` so the API process and the
Playwright worker process share one view — otherwise each would have to
discover the same outage independently, which is the redundant traffic the
breaker exists to prevent.

While the circuit is open: no calls go out, deterministic CareerOS runs
normally, offline work stays queued, and applications do not fail.

---

## Caching

Cache keys are built from everything that changes the answer:

```
task · model · prompt version · schema · temperature · system · prompt · cache_parts
```

`cache_parts` carries identity that is not verbatim in the prompt — the resume
corpus fingerprint and the normalised job-description hash. The JD hash collapses
whitespace first, so a re-scrape with different line wrapping is recognised as
the same posting rather than paid for twice.

Bumping a `*_VERSION` in `schemas.py` invalidates cleanly. In-flight dedupe means
two callers asking the identical question at the same moment share one API call.

---

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | — | absent means the layer is simply unavailable |
| `CAREEROS_GEMINI_ENABLED` | `on` | master switch |
| `CAREEROS_GEMINI_MODEL` | `gemini-flash-lite-latest` | flash-lite has a separate, larger free-tier allowance than flash |
| `CAREEROS_GEMINI_CONCURRENCY` | `1` | in-flight requests |
| `CAREEROS_GEMINI_MIN_INTERVAL_SECONDS` | `2.5` | spacing between calls |
| `CAREEROS_GEMINI_MAX_ATTEMPTS` | `4` | attempts per request |
| `CAREEROS_GEMINI_FAILURE_THRESHOLD` | `4` | failures before the circuit opens |
| `CAREEROS_GEMINI_COOLDOWN_SECONDS` | `300` | initial cooldown |
| `CAREEROS_GEMINI_MAX_COOLDOWN_SECONDS` | `900` | cooldown ceiling |
| `CAREEROS_GEMINI_TAILORING` | `on` | set `off` to keep tailoring purely local |
| `CAREEROS_GEMINI_CACHE` | `on` | disk cache |

---

## Diagnostics

`GET /gemini/status` — health pill: `HEALTHY`, `RATE LIMITED`, `CIRCUIT OPEN`,
`DISABLED`.

`GET /gemini/diagnostics` — everything: requests, API calls, cache-hit rate,
queue depth by priority, per-task counts, success rate, 429/503/404 counts,
retries, circuit state, latency average/p50/p95, tokens, estimated cost,
fallback count, and applications sent to Review because Gemini was unavailable.

`POST /gemini/metrics/reset`, `POST /gemini/circuit/close` — operator actions.

No API key, or any part of one, is ever returned. `configured` reports only
whether a key is present.

The page is at **`/diagnostics/gemini`** ("Gemini Layer" in the sidebar).

---

## Classification of every existing LLM call site

The brief was not to put Gemini everywhere it would fit. This is what each
existing call site was assessed as.

### Optional Gemini enrichment — changed

| Call site | Was | Now |
|---|---|---|
| `structured_answer_engine.resolve_level_3_llm` | local model only | **Gemini first, local second, Review third** |
| `llm_answer_generator.generate_theory_answer` | local model only | **Gemini first, then existing fallbacks** |
| `resume_diff_service._complete_batch` | local model, Gemini-as-fallback inside `LLMClient` | **Gateway-managed Gemini first, local second** |
| `matchlab/teacher.py` | its own httpx client, throttle and retry loop | **routed through the gateway at lowest priority** |
| *(new)* `autopilot_runner` pre-apply gate | did not exist | **ambiguity check, then optional Gemini second opinion** |

### Keep — deterministic already, or local is correct

| Call site | Why |
|---|---|
| `profile_answer_resolver`, `ats_plugin_reference` | pure profile lookups. Correct, instant, and the one place a model must never be involved |
| `question_classifier`, `answer_classification` | deterministic classification with a test suite behind it |
| `mistral_resume_match`, `queue_preprocessor` scoring | bulk scoring of hundreds of postings. Sending every posting to Gemini is slower, quota-bound and no more correct on the cases the local path already gets right |
| `mapping_pipeline` (`create_mapping_client`), `semantic_field_resolution` | runs inside the Playwright worker against live DOM, needs low latency and no network dependency mid-form |
| `field_mapping_agent`, `qwen_form_reviewer` | same — form-time, latency-sensitive |
| `autopilot_self_healer`, `repair_agent`, `adaptive_browser_recovery` | self-healing is explicitly wanted on the *local* model for unattended overnight runs |
| `error_normalizer` | already has a fully deterministic fallback and classifies into a fixed enum; a bigger model buys nothing |
| `tracker/classification` | rule-based first, LLM only when no rule matches. Already the right shape |
| `resume_intelligence/qwen_services` | user-initiated, local-first, and not on any submission path |

### Deterministic instead — no model at all

| Call site | Why |
|---|---|
| Role-family detection for the ambiguity gate | keyword scanning, microseconds, runs on every posting |
| Job-description fingerprinting for cache keys | a hash, not a judgement |
| Title redaction for teacher labels | must be exactly reproducible, so it is regex, not a model |

### Remove

Nothing was removed. The `LLMClient` chain still carries its own Gemini fallback
for call sites this layer does not cover; that is a known duplicate path and is
listed under remaining risks below.

---

## Testing

`tests/test_gemini_gateway.py` — 55 tests, no network, no quota spent.

Every failure mode is faked. Proving 429 handling by actually exhausting a rate
limit would burn the quota the feature exists to exploit and would prove it once,
on one day's limits.

Covered: healthy enrichment; 429 retry; sustained 429 opening the circuit;
`Retry-After` honoured; 503 retry and circuit; 404 costing exactly one call and
blocking the next; other 4xx failing fast; circuit open returning promptly;
half-open probe closing the circuit; ambiguous match with Gemini down going to
Review; confident match making zero calls; Gemini diverting to Review but never
forcing an apply; low-confidence Gemini not overriding the deterministic result;
cache hit; concurrent dedupe; prompt-version and source-data invalidation;
unparseable output; schema violation; malformed not opening the circuit; fenced
JSON accepted; benchmark traffic not starving an application; grounding
accepting supported claims and rejecting invented technologies and metrics; and
eleven deterministic field types refused before a request is built.

The suite as a whole runs with `CAREEROS_GEMINI_ENABLED=0` and a blank key, so
no test can reach the real API by accident.
