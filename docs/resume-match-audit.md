# Resume-to-JD matching audit

Tested 12 additional saved job descriptions across backend, infrastructure, databases, security, frontend, Android and ML roles. This was a read-only audit: no production scoring configuration, application thresholds, corpus approval flags or resume content was changed. No paid API was called.

## Does tailoring improve the match?

**No improvement was observed in this sample.** All 12 outputs retained all 24 approved bullets, were byte-identical to the approved PDF, and remained one page. Both existing deterministic scorers were recomputed separately on the baseline and the actual rendered output; all deltas were zero. This is not an assertion that the baseline perfectly matches these jobs. No reviewed alternative cleared the replacement policy.

The candidate-fit score below includes the profile and accomplishment corpus; it is not a score for the PDF alone. The corpus evidence score is a separate algorithm and returned zero for every case. Neither number is a verified employer ATS score or hiring probability.

| Saved posting | Candidate fit before | After | Corpus before/after |
|---|---:|---:|---:|
| Oscar — Senior Software Engineer, Backend | 81.3 | 81.3 | 0 / 0 |
| Oscar — Senior Software Engineer, Cloud Infrastructure / SRE | 82.3 | 82.3 | 0 / 0 |
| Sqsp — Software Engineer, Frontend | 33.0 | 33.0 | 0 / 0 |
| Nextdoor — Senior Software Engineer - Android | 43.8 | 43.8 | 0 / 0 |
| Anduril — Staff Software Engineer, Security | 67.4 | 67.4 | 0 / 0 |
| Chime — Senior Software Engineer, Machine Learning Platform | 36.9 | 36.9 | 0 / 0 |
| Cloudflare — Senior Software Engineer, Distributed Databases | 32.7 | 32.7 | 0 / 0 |
| Faire — Staff Machine Learning Platform Engineer | 36.2 | 36.2 | 0 / 0 |
| Figma — Software Engineer - Distributed Systems | 68.0 | 68.0 | 0 / 0 |
| Robinhood — Software Engineer, Backend | 43.5 | 43.5 | 0 / 0 |
| Robinhood — Staff Software Engineer, DevX (Developer Infrastructure) | 33.3 | 33.3 | 0 / 0 |
| Airbnb — Senior Software Engineer, Infrastructure | 37.6 | 37.6 | 0 / 0 |

## Confirmed problems

1. **No PDF-specific before/after scoring is wired into tailoring.** `generate_role_tailoring_diff` retains the stored eligibility score and correctly labels `matchRescored: false`. That avoids fake improvement, but a separate submitted-document match diagnostic is missing. `tailored_match.score_tailored_resume` has no production caller. Its legacy employer-section replacement/append logic no longer describes the actual minimal-change PDF and should not simply be reconnected.
2. **Direct resume evidence can score zero.** In `match_engine`, a direct text match is categorized as unsupported unless an evidence/verified-metric metadata entry explicitly proves the keyword. Direct-only evidence adds zero to the score. The controlled resume “Built Kubernetes Python services.” scored zero for “Required: Kubernetes Python.” All 12 real cases also scored zero. This mixes evidence verification with document relevance.
3. **Qualification matching is too permissive, and short skill names disappear.** The fallback `match_job` marks an entire qualification matched when any token overlaps. A candidate containing only “experience” received 100% coverage for a compound Rust/embedded-avionics requirement. The shared tokenizer discarded Go and C# while retaining C++. Conversely, absent recognized qualification headings cause required coverage to become zero rather than unknown/not assessed.
4. **The local-model evidence guard accepts substrings.** `_is_evidenced("Go", "built django services", set())` returned true. Whole-term matching is needed; raw substring matches cannot prove a programming language.
5. **The resume-text cache can be stale.** Its key uses attachment id, timestamp and base64 length, rather than a content hash. Two different equal-length attachments with the same id and absent timestamp returned the first text in the controlled cache probe.
6. **Scoring context can omit requirements.** The local-model scorer truncates the JD to 4,500 characters and candidate context to 7,000. A captured request lost a critical requirement placed after a long company introduction. The 12 JDs contained 4,877–10,196 characters. Keyword extraction also favors the first encountered words, which can be company boilerplate.
7. **A fast keyword-only replacement is insufficient.** The experimental boundary-aware diagnostic correctly distinguished Go from Django and retained Go/C#/C++. It nevertheless counted “I have no Kubernetes experience” as Kubernetes evidence. Its percentages concern only a small fixed technology vocabulary, not complete qualifications. It is a benchmark prototype, not production-ready scoring.

## Measured performance

| Path | Warm median | Interpretation |
|---|---:|---|
| Existing deterministic candidate-fit scorer | 4.30 ms | Fast, but the qualification/token bugs above remain. |
| Existing corpus evidence scorer | 22.75 ms | Fast, but produced all-zero evidence scores in this sample. |
| Experimental whole-term technology diagnostic | 5.94 ms | Fixes short-name/boundary probes; fails negation and is not a full matcher. |
| Minimal tailoring with cached local embeddings | 872.24 ms | Includes baseline selection; not directly comparable to a complete match-score implementation. |

First tailoring request took 16.15 seconds including local model startup. Warm medians exclude that first request. Timings are observations on this machine, not guarantees.

## Recommended efficient design

1. Keep eligibility filtering and overall candidate fit separate from **evidence present in the exact PDF**. Recompute the latter on baseline and rendered output using the same extracted JD requirements. Identical PDF hashes must yield identical scores; reordering alone should not invent new coverage.
2. Parse required/preferred criteria once, remove boilerplate, and represent compound criteria as individual conditions. Use full/partial/missing/uncertain evidence labels with exact source quotes. Treat missing qualification sections as unknown, and show extraction confidence rather than silently assigning zero.
3. Reuse the existing BM25 + cached MiniLM + RRF modules to retrieve a few relevant source sentences per criterion. Keep whole-token/phrase matching for precise technology names, quantities, experience and explicit negations. Embeddings retrieve related text; similarity alone must never certify that a claim is supported.
4. Keep verification status separate: an approved PDF sentence is direct document evidence even if no corpus metric object exists. Only approved variants/reviewed achievements may become replacement candidates. Continue the incumbent advantage, MMR, 15% improvement threshold and one-page/format preservation.
5. Cache by SHA-256 of PDF bytes + normalized JD requirements + scorer/model/configuration version. Cache requirement parsing and embeddings separately. If there is no content change, reuse the baseline match result. This avoids repeated PDF parsing and repeat full-JD model calls.
6. Use the small cached embedding model for routine retrieval; do not load a generative local model for every comparison. Ollama reported no loaded models during this audit. Its generative scoring latency was not benchmarked, and no claim of measured speedup over it is made.
7. Validate against a manually judged sample before using a new score for automatic application decisions. Add invariant tests for unchanged documents, stronger approved replacements, missing/negated skills, compound requirements, boilerplate, aliases, tail-position requirements and cache invalidation. Keep existing submission thresholds unchanged until calibration is complete.

## Validation scope

46 existing tests passed across tailored matching, queue ranking, minimal tailoring and resume intelligence. Those passing tests do not cover all the controlled failures found here. The audit script is `tools/audit_resume_matching.py`; detailed local observations are in `tmp/resume-match-audit/results.json`. It reads the database in read-only mode and compares saved posting snapshots, not current online job availability.

## Additional controlled comparisons

A synthetic fixture (not the user's resume or corpus) exercised a genuine
approved replacement that added a previously absent Python skill. Minimal
tailoring made one REPLACE and three KEEP decisions. Recomputing document-input
candidate fit increased the score from **69.9 to 72.0**. The corpus matcher
remained **0 to 0**. This shows the replacement path can introduce relevant,
authored evidence and the existing candidate heuristic can respond, but does
not establish calibrated scoring accuracy or imply a gain for the real JDs.

A separate cached MiniLM experiment compared a Kubernetes recovery requirement
against positive evidence, explicit negation, and unrelated Android work:

| Sentence type | Cosine similarity |
|---|---:|
| Positive production-recovery evidence | 0.710 |
| Explicitly says no experience with that requirement | 0.722 |
| Unrelated Android work | -0.019 |

Raw embedding similarity is therefore insufficient to certify evidence. Use it
for retrieval, then apply clause-level support, negation, quantity and source
checks. The first four-sentence embedding call took 14.25 seconds including
startup; retrieving the same cached vectors took 0.055 ms. The latter is a cache
lookup measurement, not the cost of scoring a new job. Process memory was not
successfully measured, so no memory reduction figure is claimed.

For efficient deployment, share one bounded local embedding worker between
matching and tailoring, reuse revision-keyed vectors, and make idle unloading
configurable. Avoid separate model copies per request or per matching surface.
Production changes are recommendations from this audit, not silently applied
changes to the current job/application scoring behavior.


## Implemented follow-up and final validation

The shared document-support scorer now evaluates the actual rendered PDF against extracted JD criteria, with exact evidence quotations, content-keyed caching, short-skill boundaries, negation handling, unknown/partial states and optional local semantic retrieval. It is a document evidence diagnostic, not an ATS or hiring-probability estimate. Submission eligibility remains separate.

Resume Studio exposes OFF, HONEST and AGGRESSIVE plus a per-request Fast local option that loads no model and preserves saved configuration. AGGRESSIVE broadens source-backed selection; it does not invent numbers or skills. Safe reordering now compares every compatible slot within a role, including non-adjacent bullets, rather than only neighbours. An approval checkbox in each accomplishment's Resume variants section enables reviewed current bullets as replacement candidates; editing the current bullet clears that approval. Metric verification and claim restrictions still apply.

`tools/audit_resume_modes.py` reproduces a read-only comparison of 12 saved JDs across all three modes. The final 36 PDFs were all one page: OFF changed 0/12, HONEST reordered 5/12, AGGRESSIVE reordered 12/12 (2–9 bullets each). Content-support scores did not increase, as expected for reordering identical claims. None of the 52 stored accomplishments had explicit replacement approval during this audit, so no real-corpus replacements were made. Controlled reviewed-evidence regressions verify that materially stronger evidence replaces a weak slot and weaker or unapproved evidence does not.

The local browser integration check used isolated read-only test services, because the regular dashboard/API were not running. All three modes returned one-page output: OFF 278 ms, HONEST 459 ms, AGGRESSIVE 898 ms in Fast local mode for the checked descriptions. PDF download, stale-input protection and mobile overflow checks passed. The non-adjacent reorder regression checks unchanged pixels outside allocated changed slots. Web typecheck passed.

The required Autopilot runner regression set now passes 18/18 checks. Its outdated fixtures were updated for continuous batch rollover and the current NEEDS_REVIEW outcome. Successful-render fixtures write only to pytest temporary storage; added failure cases assert that render failures, low scores without override, and stopped jobs cannot reach an employer. No production submission guard was changed.
