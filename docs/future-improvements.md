# Future improvement ideas

Not implemented. This is a research-ready backlog: each item states what it is, why it's a
real gap today, where it would plug into the existing codebase, and open questions worth
resolving (often by reading around online) before writing any code.

Several of these already exist as one-line entries in `docs/roadmap.md` (Phase 3's "Follow-up
reminders" / "Interview prep" / "Mock interview scaffolding", Phase 4's "Skill gap analysis").
This document is the implementation-level detail the roadmap doesn't carry.

## Borrowed from ai-job-search

Surveyed from [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search) — a
Claude-Code-workflow project (markdown slash commands + small CLI helpers a human runs
interactively), not a standalone app. No code there is directly portable to CareerOS's
FastAPI/Next.js architecture, but four of its capabilities are real gaps here.

### 1. Stale-application follow-up drafting

**What**: after N days of silence on a `SUBMITTED` application, draft — never auto-send — a
follow-up email. The source project grounds the draft strictly in claims already made in that
application's own submitted materials, so it never invents new information mid-thread.

**Why it's a gap**: CareerOS tracks application status (`aa_autopilot_job`, the tracker UI) but
nothing watches for silence and proactively surfaces a drafted next step. Today, a stale
application just... sits there.

**Where it'd plug in**: a scheduled check over `SUBMITTED` jobs past their silence window,
surfacing a draft in the tracker UI (`apps/web` application detail view) or as a notification.
Drafting itself would reuse the existing resume-tailoring LLM path
(`apps/api/app/services/resume_intelligence/`) rather than a new one.

**Research questions**:
- What's a sensible default silence window, and should it vary by ATS (Greenhouse vs. Lever
  vs. a direct company career page tend to run different typical response times)?
- Should the window adapt to signals like company size or how many other candidates the role
  has moved (if that's ever observable)?
- How to keep the tone right — look at what recruiters themselves say makes a follow-up read as
  confident vs. desperate vs. templated; this is a genuinely well-covered topic in career-advice
  writing and worth a proper read before drafting a first version.

### 2. Post-submission interview prep pack

**What**: once an application gets a response, generate a prep pack built from *that specific
application's* actual tailored resume, cover letter, and company research — plus behavioral
answers mapped to the STAR format, optionally with a mock-interview roleplay.

**Why it's a gap**: pure gap — CareerOS has nothing today for what happens after a reply
arrives. This is also literally roadmap Phase 3 ("Interview prep", "Mock interview
scaffolding", "Behavioral story bank") and the unbuilt "Interview OS" module — this write-up is
the detail behind those three lines.

**Where it'd plug in**: a new prep-pack generator keyed off an application id, pulling its
already-stored tailored materials (`aa_application_draft`, `aa_pre_submit_report` entities) plus
the existing accomplishments/story-bank data (`accomplishment` entities, already used by
`resume_intelligence`) rather than asking the user to re-enter their own history.

**Research questions**:
- How to source realistic interview questions for a specific company/role — LLM-generated from
  the JD alone tends to be generic; aggregated real questions (Glassdoor-style) are richer but
  raise a data-sourcing question worth resolving first.
- What UX for a mock interview actually helps — text chat is simplest to build; voice is more
  realistic but a much bigger lift. Look at what dedicated interview-prep products ship before
  picking.
- How to keep STAR answers grounded in the user's real accomplishments rather than the model
  filling gaps with plausible-sounding fabrication — this is the same "no fabrication" invariant
  the resume/cover-letter pipeline already enforces elsewhere in the codebase, so whatever
  guardrail pattern exists there should extend here rather than a new one being invented.

### 3. Richer Gmail parsing for outcomes

**What**: CareerOS's current Gmail integration (see `docs/email.md` and the
`verify-gmail-application-confirmation` workflow) only confirms a submission went through.
Extend it to also detect and classify interview invites, assessment/coding-challenge links,
offers, and rejections, proposing each as a batch for human approval before writing anything to
the tracker — citing the source email each time, the same way submission confirmation already
does.

**Why it's a gap**: real signal is sitting in the inbox unread by the system. Every outcome
CareerOS currently learns about, it learns about because a human noticed and updated the
tracker by hand.

**Where it'd plug in**: extends whatever the existing Gmail-confirmation code path already does
(same account, same read scope) — this is additive classification on top of a channel CareerOS
already reads, not a new integration.

**Research questions**:
- Classification approach: LLM-based (feed subject + snippet to the local/Gemini model already
  in use), rule-based sender/subject heuristics, or a hybrid where heuristics gate an LLM call
  only on ambiguous cases (cheaper, matches the deterministic-first-then-LLM pattern the rest of
  CareerOS already follows).
- How Teal, Huntr, and Simplify Copilot handle this today (they all advertise some version of
  auto-logging outcomes from the inbox) — worth a closer look at what they get wrong before
  copying an approach.
- False-positive risk and batch-approval UX: proposing 10 items per day for one click each is
  fine, proposing something wrong that silently corrupts a tracker record is not — the
  human-approval-before-write pattern from the source project is the right default to keep.

### 4. Skill-gap heatmap from rejected/low-fit postings

**What**: aggregate postings the matcher scored low on or that were explicitly rejected,
extract which required skills kept recurring as the gap, and turn that into a prioritized
learning plan with rough time estimates.

**Why it's a gap**: CareerOS's matcher (Ollama qwen3:4b primary, Gemini second-opinion gate,
deterministic heuristic fallback) already produces a rich signal about *why* a posting didn't
match well — that signal is currently thrown away once a job is marked `INELIGIBLE` or
`NEEDS_REVIEW`. This is Phase 4's "Skill gap analysis" line item, detailed.

**Where it'd plug in**: a batch job over `aa_discovered_job`/`aa_job_match` entities with a low
`matchScore`, extracting `missingSkills` (already a field on match results — see
`candidate_match_context.py`) and aggregating by frequency.

**Research questions**:
- How reliably `missingSkills` extraction generalizes across unstructured JDs — worth checking
  whether the existing extraction is already good enough as an input, or whether a dedicated
  structured-skill-extraction pass is needed first.
- Prioritization: raw frequency, weighted by how senior/high-value the roles asking for it were,
  or weighted by how close the candidate already is (a skill mentioned as "nice to have" vs. a
  hard blocker)?
- Whether to link to specific learning resources (curated, goes stale) or keep the plan generic
  (durable, less immediately actionable) — a genuine product tradeoff, not just an engineering
  one.

### Smaller item: portable robots.txt checker

`tools/robots_check.py` in the source repo is a small, stdlib-only RFC 9309 robots.txt gate. It
correctly distinguishes a 403 from a WAF (not a robots signal) from a real `Disallow` entry, and
avoids a known blank-line parsing bug in Python's own `urllib.robotparser`. CareerOS's scrapers
under `apps/api/app/services/job_discover/` don't appear to check robots.txt at all today. This
one is close to directly portable — not a research item, just worth reading the source file and
adapting it into the scraping path (likely `aggregator_resolve.py` and the per-source scrapers
in `job_discover/sources/`).

## From web research

Searched for 2025–2026 developments in AI-driven job search agents, resume/JD matching
research, ethical bot-detection handling, and feature sets from adjacent commercial products.
Excluded anything CareerOS already does well: multi-source scraping, local+cloud match scoring
with a second-opinion gate, BM25/fusion retrieval, resume tailoring with quality gates,
Playwright application automation with DOM verification and self-healing, Greenhouse
verification-code handling, Gmail submission confirmation, dedup/tier-guardrailed batching.

### LLM re-ranking for resume-job matching (ConFit v3)

**What**: a 2026 technique ([ConFit v3, arXiv:2605.09760](https://arxiv.org/html/2605.09760v1))
that re-ranks candidate matches with a *sliding-window, multi-pass* LLM pass rather than scoring
everything in one shot — repeatedly re-ranking within a window of ~4 items and sliding it, with
two passes measurably beating one (nDCG@10 57.96 vs. 55.41 in their eval). Fine-tuned via SFT
distillation from a larger model plus RL with listwise rewards, on top of Qwen3-8B/32B — the
same model family CareerOS already runs locally at 4B.

**Why relevant**: CareerOS's matching pipeline already has a BM25/fusion retrieval stage plus an
LLM scoring stage (`qwen_job_match.py`) and a Gemini second-opinion gate for ambiguous cases —
structurally similar to a retrieve-then-rerank pipeline, just not built around this specific
multi-pass re-ranking technique.

**Research questions**:
- The paper only evaluates 8B/32B models; it's an open question whether the sliding-window
  re-rank approach holds up at the 4B scale CareerOS runs locally, or whether this would need to
  be a job for the Gemini fallback specifically rather than the local model.
- Whether the training data / fine-tuning effort (SFT distillation + RL) is worth reproducing at
  all versus just adopting the *prompting pattern* (sliding-window multi-pass) zero-shot against
  the existing models — likely the cheaper first experiment.

### Salary negotiation assistant

**What**: once an offer arrives, help draft a counter and rehearse the conversation.
Commercial tools in this space (Four-Leaf, and DIY approaches people describe using ChatGPT)
converge on a similar shape: benchmark comp for the role/level/location, target the ~75th
percentile with a floor around the 50th, then rehearse objection-handling via a few practice
rounds before the real call.

**Why relevant**: pairs naturally with item 3 above (Gmail outcome parsing) — an "offer"
classification is exactly the trigger this would key off. Distinct from resume/cover-letter
generation; nothing in CareerOS today touches post-offer negotiation.

**Where it'd plug in**: triggered by the Gmail-parsing offer signal (once that exists), drafting
against comp-benchmark data (source TBD — this needs either a data provider or a research pass
on what's freely available) plus a rehearsal/roleplay loop similar in shape to the mock-interview
idea in item 2.

**Research questions**:
- Where does comp-benchmark data come from without a paid data provider — this is probably the
  single biggest open question for this feature.
- Whether the rehearsal loop should share infrastructure with the mock-interview roleplay from
  item 2 rather than being built separately.

### Reduce CAPTCHA/bot-detection trigger rate, not just react to it

**What**: request pacing and interaction patterns that make automation less likely to *trigger*
a bot-detection challenge in the first place — randomized delays between actions, avoiding rapid
consecutive requests against the same board — rather than only handling the block once it
happens.

**Why relevant**: this session's own investigation found bursts of consecutive reCAPTCHA hits
against the same board in quick succession (e.g. several OpenAI Ashby postings back-to-back).
CareerOS's current posture (correctly, per its own transparency principles) is to treat a
CAPTCHA as a hard stop and stage the job for the human — that's the right terminal behavior and
shouldn't change. What's worth adding is reducing how often that wall gets hit at all, which is
a request-pacing question, not a circumvention one. General web-scraping guidance converges on
the same two levers: respect `robots.txt` (see the portable checker above) and avoid
rapid-fire consecutive requests.

**Research questions**:
- Whether CareerOS's current request cadence against a single board during a queue-refill burst
  is already reasonable or measurably bursty — worth instrumenting before changing anything.
- What pacing strategy other ethical scraping guides recommend as a concrete default (fixed
  delay vs. randomized-with-jitter vs. adaptive backoff after a first block on a given board).

### Considered and explicitly not recommended: real-time "interview copilot"

Several commercial tools (marketed as "Interview Copilot" features) feed the candidate live
suggested answers during an actual interview call. This is a capability gap relative to some
competitors, but it's a poor fit for CareerOS and is being noted here specifically so it doesn't
get rediscovered and built naively later: it's undisclosed real-time assistance during a live
evaluation, which sits at odds with the transparency/human-supervision principles the rest of
this codebase is built around (see `docs/application-assistant.md`'s "human-supervised" framing
and the Gemini layer's disclosure-first design in `docs/gemini-enrichment-layer.md`). The
mock-interview *practice* feature in item 2 above is the legitimate version of this idea —
rehearsal before the call, not assistance during it.
