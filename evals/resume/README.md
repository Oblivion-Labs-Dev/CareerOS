# Resume compiler evals

Synthetic job descriptions, one per target role family, scored against `career.json` by
`apps/api/app/services/career_compiler/evals.py`.

```text
npm run eval:resume            # live: DeepSeek + Word, JD -> DOCX/PDF, all metrics
npm run eval:resume -- --offline   # JD parsing, retrieval and planning only
npm run eval:resume -- --only backend security
```

Each fixture in `fixtures/` lists:

* `jd`: the posting (synthetic).
* `expected_requirements`: phrases jd.json must extract.
* `expected_projects` / `expected_evidence`: career.json IDs retrieval should offer and the resume should use.
* `must_not_use`: evidence that must never be cited (every `needs_reconciliation` record is added automatically).
* `must_not_say`: technologies, titles or numbers the posting asks for that career.json does not support.
* `expected_gaps`: skills that must stay unclaimed and appear as "no supported evidence".

A fixture fails on any shipped hallucination, conflict leakage, precision below 1.0, a page count other than one,
template drift or a failed PDF check. Results (with model, prompt, retrieval, query and template versions and the
career.json hash) go to `results/<timestamp>/report.json` and `results/latest.json`; they are not committed.
