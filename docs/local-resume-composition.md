# Local resume composition

Resume building and application tailoring now use the same CPU-only composer.
No LLM server, GPU allocation, API key, embedding download, or external request
is needed for these two paths. Other CareerOS features retain their own model
settings; this change does not disable job matching or application assistants.

## Pipeline

1. Read current database accomplishments and profile experience.
2. Preserve job-description clauses and distinguish required, preferred,
   responsibility, and target-role requirements using local rules.
3. Retrieve complete authored bullets, published variants, and candidate
   sentences from behavioral stories. Never splice claims across stories.
4. Gate candidates by vocabulary/technology-alias overlap with each requirement,
   same as before. Among gated candidates, rank by BM25 and (if a local
   sentence-embedding model is available) semantic similarity, fused with
   Reciprocal Rank Fusion; multiply by a deterministic quality score (verified
   metrics, action/result structure, technical specificity, reviewed source)
   and a professional/personal-project tier weight. Select with Maximal
   Marginal Relevance so results stay relevant without repeating the same
   point, using each candidate's fused relevance per estimated line of page
   space as the value term. `requirementCoverage` is still computed purely
   from vocabulary/tag overlap of what was selected - ranking signals never
   touch that number, so it stays a word-overlap estimate, not a model score.
5. Return exact source text with accomplishment/story identity, a content revision,
   structured facts, selection reasons, partial requirements, review warnings,
   and a debug block per bullet (BM25/semantic rank, RRF score, quality score,
   diversity penalty, matched requirement/tag ids) for auditing a selection.
6. Render a flowing PDF from the profile and selected achievements. Check the page
   count. Personal projects remain separate; dates and education come from the profile.

The frontend supports draft PDF downloads with a visible draft label. Unverified
metrics, unclassified evidence, extracted narrative sentences requiring review,
and potentially conflicting claim restrictions block application-ready export.
The existing application eligibility score and submission gates are preserved.
Lexical evidence coverage is labeled as an estimate, never an ATS probability.

## Evidence maintenance

The database is the live source of truth. The JSON corpus is an import source.
The story map no longer keeps an indefinitely cached copy of the JSON file.
Accomplishment saves merge existing fields and retain previous snapshots.
Imported story bodies refresh only when they still equal their previous imported
version; local edits are preserved, and previous imported bodies are retained.
Legacy resumeEvolution.current and metricMetadata fields are supported alongside
the newer currentBullet, metrics, and published resumeVariants schema.

For better writing without ongoing model inference, edit reusable current bullets
or publish variants once per achievement. Behavioral narratives can supply draft
sentences; they are not automatically polished resume writing. Correct or verify
metrics in the evidence record before publishing the resume.

## Ranking internals

- `bm25.py` - Okapi BM25 over the same tokenizer as the rest of the composer.
  Pure Python; the candidate pool is tens of records, not thousands, so no
  vectorized implementation is needed.
- `semantic.py` - optional local embeddings via
  `sentence-transformers/all-MiniLM-L6-v2`, CPU only. Embeddings are cached in
  memory by `(accomplishment revision hash, exact text)`, so recomposing the
  same evidence against a new job description - or the one-page-fit retry loop
  in `resume_studio.py`, which recomposes several times per request - re-runs
  the model only for genuinely new text. If the package or its cached model
  weights are unavailable, every function returns `None` and callers fall back
  to BM25 + skill-taxonomy matching alone; nothing raises for a missing model.
  A real ONNX/int8 export was skipped for now since `sentence-transformers` and
  a CPU PyTorch build were already present in this environment and satisfy the
  same constraint (CPU-only, no network at request time); revisit if model
  load time or memory become a real problem.
- `fusion.py` - Reciprocal Rank Fusion (`k=60` by default) combines the BM25
  and semantic rank orderings per requirement without mixing their
  incompatible raw score scales.
- `quality.py` - deterministic bonuses/penalties (verified metric present,
  action-verb opening, technical-tag density weighted by `story_index`'s
  technology/concept/behavioural category, vague-language penalty). Multiplies
  the fused relevance; never changes which candidates are eligible.
- Selection uses Maximal Marginal Relevance (`lambda≈0.75` by default): at each
  step, prefer high relevance-per-estimated-page-line, penalized by the
  candidate's similarity (semantic cosine, or word-Jaccard when embeddings are
  unavailable) to bullets already picked. The existing ReportLab render-and
  retry loop in `resume_studio.py` is unchanged and remains the actual
  one-page authority; MMR only changes which bullets are offered to it and in
  what order.

All of `bm25_k1`, `bm25_b`, `rrf_k`, `mmr_lambda`, and `use_semantic` are
keyword arguments on `compose()` with the defaults above, for tuning or for
tests that want a fully deterministic, embeddings-off run.

## Efficiency and alternatives

The composer uses bounded caches for token/tag extraction and semantic
embeddings. A local 52-record benchmark measured roughly 0.04-0.17s per
composition once the embedding model is warm (a one-time ~10-15s load per
process, or ~300MB additional RSS, the first time any composition runs with
semantic ranking enabled). These are observations, not latency guarantees. Run
`tools/benchmark_local_resume.py` to reproduce measurements against the stored
seed and story imports.

Remaining known weaknesses:

- The semantic layer only re-ranks candidates that already pass the lexical/
  tag overlap gate; it deliberately cannot pull in a bullet with zero shared
  vocabulary, even a true paraphrase. This keeps `requirementCoverage` honest
  and prevents an embedding false-positive from smuggling in an unrelated
  claim, but it means very loosely-worded requirements still show as
  uncovered even where a human would recognize the fit.
- BM25's document-frequency statistics are recomputed from whatever candidate
  pool is passed in on each call (tens of records), not against a larger
  reference corpus, so idf weighting is a within-request signal only.
- A single small model (`all-MiniLM-L6-v2`) does not resolve deep domain
  jargon (e.g. mapping "sovereign cloud" to "IL5/GCC High" without a shared
  token) any better than the existing tag vocabulary already does by hand.
- A small quantized local model for an occasional single-bullet rewrite
  remains a possible future layer, but is not implemented: supply only one
  achievement and one requirement, constrain JSON output, cap context and
  output, and require review before saving a reusable variant.
  https://ollama.com/library/qwen3:1.7b
  https://ollama.com/blog/structured-outputs

No paid cloud fallback is part of resume composition. Local lexical and
embedding matching is still less capable of understanding nuanced,
unconventional requirement phrasing than a strong language model;
partial/uncovered requirements and source review remain visible for that
reason.

## Resume Studio

Open `/profile/resume-studio` from the Resume & Profile tabs. Paste a job
 description, optionally enter the role and company, and generate a preview.
The studio uses the shared composer and preserves its ranking defaults,
including optional semantic matching. It calls no paid generation API.

The classic layout follows the original resume, merges current profile details,
and checks that the rendered PDF has exactly one US Letter page. The preview
is rendered from that same PDF; Download PDF returns those exact bytes. Source
evidence and review notices appear below the preview. Changing the inputs
requires regeneration before downloading.

If the running API predates the studio endpoint, the web route reads authenticated
profile and accomplishment snapshots and uses the same composer in a local
worker. This avoids interrupting active applications. The worker reuses its
cached local model for repeat requests, allows one generation at a time, and
exits after two idle minutes to release memory. It uses cached model files
without downloading new weights. A cold first request can take longer.


## Minimal-change tailoring (current default)

Resume Studio, resume generation/tailoring, and application resume PDFs now use
`minimal_tailoring.py` and `baseline_document.py`. The older `compose()` remains
available as an explicit corpus-composition utility and for comparison tests;
it is no longer the tailoring default. Existing BM25, semantic, RRF, quality,
and MMR modules are retained.

The authority is the server-configured `CAREEROS_APPROVED_RESUME_PATH`, or
`apps/api/data/approved-resume.pdf` when unset. The supplied approved resume was
copied to this ignored local data file. The original source file is unchanged.
No private resume is committed. Missing or unsupported baselines fail closed
instead of silently rebuilding a resume. Updating the approved file invalidates
previous result hashes. Current profile fields do not overwrite approved PDF
content during tailoring.

Bullets retain positioned lines and rich-text spans: font, size, weight, color,
origin and bounding box. KEEP returns original content; when every decision is
KEEP, the entire PDF is returned byte-for-byte. REORDER is restricted to the same
role/project with compatible line geometry and copies original PDF glyphs.
REPLACE uses exact reviewed source text, inherits the slot's bold-opening and
normal-body structure, uses embedded fonts, and must fit the existing line
baselines without shrinking. Unsupported glyphs or overflow retain the
incumbent. Section order, margins, education, skills, role counts, and bullet
markers remain untouched. The page count must remain one.

Corpus search runs only when baseline relevance identifies a weak slot. Source
priority is approved baseline, approved variant, reviewed accomplishment, then
explicitly resume-approved story sentence. A legacy record marked `current` is
not automatically reviewed. To be eligible, an accomplishment needs
`resumeApproved: true`, `reviewed: true`, or `reviewStatus: reviewed/approved`;
existing metric verification and claim restrictions still apply. Missing role
metadata is acceptable only when that employer has one unambiguous baseline
role; otherwise it cannot replace a dated-role bullet.

Replacement utility combines JD relevance, quality, source priority, MMR
redundancy, incumbent retention and replacement cost. A candidate must improve
JD relevance and exceed the configured relative utility threshold after costs.
Coverage remains a diagnostic and does not drive greedy coverage maximization.
Each result includes KEEP/REORDER/REPLACE decisions, reasons, source revisions,
baseline and document hashes, retention fraction, and effective configuration.

Set `profile.resumeTailoringConfig` to override defaults consistently across
Studio, generation, tailoring and application drafting:

```json
{
  "bm25_k1": 1.5,
  "bm25_b": 0.75,
  "rrf_k": 60,
  "mmr_lambda": 0.75,
  "use_semantic": true,
  "replacement_threshold": 0.15,
  "weak_relevance": 0.35,
  "retention_bonus": 0.12,
  "replacement_cost": 0.08,
  "max_replacement_fraction": 0.25,
  "reorder_threshold": 0.15
}
```

Optional embeddings load cached CPU weights only. Missing weights or encoding
failures fall back to lexical ranking. No paid model is called. Off mode returns
the exact configured approved PDF and cannot search for or apply replacements.

### Validation on saved job descriptions

Compared against three full saved Block postings: Senior Site Reliability
Engineer (8,079 characters), Staff Software Engineer, Cash App Banking (7,177),
and Staff Software Engineer, Go-to-Market Systems & AI (8,345). The old composer
selected 16 bullets for each. Minimal tailoring retained all 24 baseline bullets
for each; every PDF was one page with semantic matching available. No eligible
reviewed alternative justified replacing baseline content. This validates
conservative retention, not an assertion of complete JD coverage.

Synthetic regression fixtures separately exercise actual replacements,
approved-variant priority, reorder formatting, stale source hashes, unavailable
embeddings, role attribution, and overflow. Actual embedded-font swap and
replacement render checks confirmed one-page selectable text and identical
pixels outside changed slots. Live Studio generation/download returned the
minimal-change method with 24 bullets; the downloaded bytes matched its preview
source, changed-input downloads were disabled, and mobile had no horizontal
overflow.
