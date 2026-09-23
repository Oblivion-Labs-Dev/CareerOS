# Resume–job matcher benchmark

Nine approaches measured on the same labelled postings to answer one question:
**what is the cheapest architecture that decides "should CareerOS apply to this
job?" reliably enough to gate automatic submission?**

Bench lives in `apps/api/scripts/matchlab/`. The winning scorer, role-shape, now
lives in `apps/api/app/services/application_assistant/role_shape_match.py` and
orders the Autopilot queue whenever a posting has no model score (#50); matchlab
imports it from there, so this benchmark measures exactly what the queue runs.
See "Promoted into the queue" at the end.

## Constraints this was measured under

| | |
|---|---|
| RAM | 16 GB |
| GPU | RTX 2070 Super Max-Q, 8 GB VRAM |
| Inference | CPU only, so Ollama keeps the GPU |
| Models resident | one at a time, explicitly unloaded between approaches |
| Target | 851 queued jobs, low hundreds of ms per job at worst |

## Leaderboard

140 real postings, 49 with a usable label (20 APPLY, 29 SKIP). Two repeats per
approach; all were bit-identical across runs.

| Approach | ROC-AUC | PR-AUC | Gate P | Gate R | Latency | 851 jobs | Model | Adversarial |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **role-shape** | **0.950** | 0.944 | 1.000 | 0.650 | 8.3 ms | 7.1 s | 0 | 3/3 |
| hybrid-logreg (LOO-CV) | 0.934 | 0.924 | 1.000 | 0.400 | 9.2 ms | 7.8 s | ~2 KB | 3/3 |
| minilm-whole | 0.805 | 0.715 | 1.000 | 0.150 | 311 ms | 4m 25s | 87 MB | 3/3 |
| tfidf-cosine | 0.747 | 0.697 | 1.000 | 0.150 | 5.5 ms | 4.7 s | 0 | 3/3 |
| cross-whole | 0.729 | 0.731 | 1.000 | 0.300 | 88 ms | 1m 15s | 91 MB | 3/3 |
| bm25-whole | 0.707 | 0.630 | 1.000 | 0.050 | 1.8 ms | 1.5 s | 0 | 3/3 |
| bm25-sectioned | 0.690 | 0.596 | 1.000 | 0.050 | 15.5 ms | 13.2 s | 0 | 3/3 |
| minilm-evidence | 0.645 | 0.532 | 1.000 | 0.050 | 106 ms | 1m 30s | 87 MB | 2/3 |
| cross-evidence | 0.574 | 0.605 | 1.000 | 0.050 | 1338 ms | 19m | 91 MB | 0/3 |
| naive-coverage *(current)* | **0.332** | 0.359 | — | — | 121 ms | 1m 43s | 0 | 1/3 |

**Gate P / Gate R** are precision and recall at the lowest threshold that never
auto-applies to a job labelled SKIP. Auto-apply precision is the metric that
decides the architecture: sending a good job to REVIEW costs a click, while
auto-submitting a bad application cannot be undone.

### The current scorer is worse than guessing

`naive-coverage` scores **0.332**. Below 0.5 does not mean "fails to separate" —
it means it systematically ranks unsuitable postings *above* suitable ones.
Inverting its output would score 0.668. This matches the separately observed
behaviour where it rated an Android role at 85% and a backend role at 61.5%.

## Ablation: what carries the signal

| Configuration | ROC-AUC | Gate R | Adversarial |
|---|---:|---:|---:|
| family + seniority + coverage + bm25 | 0.952 | 0.700 | 3/3 |
| family + seniority | 0.945 | 0.400 | 3/3 |
| **family alone** | **0.912** | 0.400 | 3/3 |
| everything except family | 0.778 | 0.050 | 1/3 |
| coverage alone *(the old idea)* | 0.655 | 0.100 | 1/3 |

Role family is worth **+0.194 AUC**. The five other signals together are worth
**+0.022**.

Representing a posting as a *shape* — role family, seniority, weighted
requirements — rather than a bag of skills is what fixes the original failure,
where boilerplate frontend requirements (React, TypeScript, CI/CD, testing)
outscored a backend role the candidate is far closer to.

### Evidence tiering is a safety property, not an accuracy one

Sweeping the project-evidence weight from 0.0 to 1.0 barely moves ranking
(0.947 → 0.952). But at 1.0 — treating a side project as equal to production
work — the adversarial suite drops to 2/3. Tiering exists to stop "I used
Kubernetes once" reading as "I owned Kubernetes in production", not to improve
average ranking.

## Results that contradicted the hypotheses

**Evidence matching lost to whole-document scoring, with both models.**
Bi-encoder 0.645 vs 0.805; cross-encoder 0.574 vs 0.729 and 15× slower. Two
independent models agreeing makes this structural rather than an implementation
accident. Matching each requirement to its best supporting evidence *is coverage
again*, computed semantically — and coverage is exactly what fails when a generic
posting's requirements all find some support somewhere. A better matcher does not
fix a metric that asks the wrong question.

**The trained model lost to the hand-weighted formula.** Logistic regression over
six features scored 0.934 against 0.950, gate recall 0.400 against 0.650, under
leave-one-out cross-validation. With 49 labelled pairs there is not enough signal
to learn better weights than sensible priors. This argues for more labels rather
than against the architecture — the calibration benefit still stands.

## Recommended production architecture

```
JD ──► structural parse (role family, seniority, must/preferred)
       │
       ├──► hard constraints        ITAR, non-US, CAPTCHA → existing buckets
       │
       └──► role-shape score        family · seniority · weighted coverage · BM25
                    │
          ┌─────────┴─────────┐
      ≥ threshold          below
          │                   │
      AUTO APPLY           REVIEW          (nothing is ever discarded)

Resume ──► evidence tiered professional vs project ──┘
```

Deliberately absent: embeddings, cross-encoder, generative model, taxonomy
service, trained classifier. Each was measured; none paid for itself.

**Cost: 8.3 ms per job, zero model weights, ~7 seconds to rescore all 851 queued
jobs** — against roughly 21 hours for the 7B model.

### Where Mistral still belongs

Not in the matching path. It stays the accuracy reference and is the most
promising source of labels: the hybrid failed for want of training data, and an
offline teacher run over a few hundred historical postings is the cheapest way to
fix that. Human labels remain authoritative.

## Methodology bugs found and fixed mid-study

Both were the same mistake in different places — treating absent information as
a negative signal.

1. **REVIEW labels counted as negatives.** Scorers were penalised for ranking
   postings highly that nobody had classified. The apparent false positives at
   the top of the ranking were almost entirely these unknowns. REVIEW is now
   excluded from the binary metrics.
2. **Corpus headlines had captured chat messages.** Three stories — including
   both major Microsoft ones — had a headline like *"I will paste you everthing i
   worked on..."*, because the corpus was sliced verbatim from transcripts. That
   string was reaching the tailoring prompt and the match context, so this was a
   production bug, not just a benchmark one. Headlines are now derived by
   skipping conversational lines; bodies are untouched.

## Limits

- **49 labelled pairs, none human-confirmed.** Labels are title-derived. This is
  the weakest part of the study and the first thing to strengthen. The harness
  records `needs_human` and `label_source`; human labels override rule-derived
  ones.
- **Role-family detection is tuned to one candidate.** The cue tables encode this
  résumé's domain. Fine for CareerOS, not a general matcher.
- **Gate recall 0.650** means a third of good jobs go to REVIEW. Correct given
  the precision requirement, but the number to improve next.
- **ESCO / O\*NET untested.** Taxonomy normalisation is the strongest remaining
  lead and the one most likely to raise recall without adding a model.

## Reproducing

```bash
cd apps/api

# leaderboard (add --neural for MiniLM/cross-encoder; needs torch)
.venv/Scripts/python.exe scripts/matchlab/run.py --jobs 140 --out data/matchlab_final.json

# which signals earn their place, plus the evidence-tier sweep
.venv/Scripts/python.exe scripts/matchlab/ablate.py --jobs 140

# trained model, leave-one-out cross-validated
.venv/Scripts/python.exe scripts/matchlab/hybrid.py --jobs 140
```

Raw results: `data/matchlab_final.json`, `matchlab_ablation.json`,
`matchlab_hybrid.json`.

## Promoted into the queue (#50, 2026-09-23)

**The move was checked to be exact.** Run against the database backup from 11 September
(the closest to the original run), `run.py --jobs 140` with the promoted module reproduces
the leaderboard above: role-shape ROC-AUC **0.950**, PR-AUC 0.944, gate precision 1.000 and
recall 0.650, adversarial 3/3; bm25-whole 0.707, bm25-sectioned 0.690 and tfidf 0.747 are
unchanged too. On today's data the old and new code agree on all 140 per-job scores to within
2e-14.

**One fix went in with the move.** The scorer summed floats while iterating a `set` of
strings. String hashing is randomised per process, so the same posting could score
differently after an API restart (a test shows the old code failing across `PYTHONHASHSEED`
values). Terms are now iterated in sorted order.

**Today's data reads differently, and the reasons are data, not code.** On the 23 September
database the same run gives role-shape **0.900** (95% bootstrap interval 0.79–0.98), with
only 44 of 140 jobs labelled, since the labels come from job titles. `naive-coverage` now scores
0.887: it calls the live `story_index`, which has improved since. The two are statistically
tied on this set; role-shape was chosen because it is about 25× cheaper (no database session per
job, which is what froze the API before) and deterministic. The "side-project Kubernetes"
adversarial case now ties, because the approved resume states professional Kubernetes work
("15+ containerized services using Kubernetes and AWS ECS/ECR"), which removes that case's
premise for this candidate. Its highest-scored SKIPs are non-engineering titles containing
"Platform" (product manager, designer), which the runner's title filter excludes anyway.

**Cost in the API process.** IDF is fitted once over every active posting (about 9,600,
3 s) and cached, each posting is scored once (p50 2.6 ms, max 11 ms), and a call scores
at most 500 new postings in a worker thread, yielding the GIL between them. Measured
event-loop lag during such a call: median 7 ms (idle 6 ms), p99 48 ms. Memoised calls are
indistinguishable from idle.

