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
