# CareerOS Resume Corpus — completion report

**Completed:** 2026-07-15  
**Route:** `/resume-corpus`  
**Preview:** `/resume-corpus?preview=1`

## Outcome

The Resume Corpus is now a twelve-area career-intelligence workspace with a new nested shell, a full accomplishment explorer and editor, evidence-aware resume workflows, universal search, and deterministic preview data. The canonical route is composed from new feature components; the old `*-tab.tsx`, command-palette, and legacy focus-mode files are not on its import path.

The implementation preserves the intended repository boundary: Arsenal owns domain-neutral UI primitives, CareerOS core owns portable career schemas, CareerOS UI owns reusable career presentation, and the web feature owns route state, adapters, product workflows, and persistence calls.

## Shipped surfaces

| Area | Shipped behavior |
| --- | --- |
| Overview | Alex Morgan preview hero, resume/interview readiness, twelve corpus health cards, priority actions, strongest accomplishments, research queue, and career timeline |
| Accomplishments | Seven explorer layouts: Cards, List, Table, Timeline, Kanban, Matrix, and Graph; search, filters, saved presets, and source-record navigation |
| Accomplishment workspace | Nineteen disclosure sections, readiness/gap intelligence, evidence and metric editing, reviewer concerns, interview questions, autosave, local draft recovery, undo/redo, and focused gap resolution |
| Resume Builder | Ten-step configuration, source-record ranking/selection, real job-description keyword coverage, evidence warnings, preview canvas, copy, and plain-text export |
| Job Match | Explicit evidence, inferred support, unsupported explicit claims, and missing requirements kept as separate categories |
| Interview Prep | Study, Practice, Mock, and Rapid review modes; source-linked question queue, notes, timer, and local practice state |
| Metrics | Verified/unverified rollups, accessible comparison bars, filtering, and source-record drill-through |
| Skills | Evidence-derived depth groups plus a separately labeled unverified technology inventory |
| Knowledge Graph | Deterministic bounded graph, company/relationship clustering, search, and an accessible list alternative |
| Evidence | Artifact browsing, provenance/status filtering, and typed artifact attachment in the accomplishment workspace |
| Review Center | Severity/status triage with mapped questions and resume impact |
| Templates / Settings | Template-to-builder handoff, local preferences, and profile editing through the existing profile API |

Universal search opens with Ctrl/Cmd+K and indexes accomplishments, metrics, skills, evidence, concerns, and interview questions. Results are grouped, keyboard navigable, and open their source record or destination area.

## Shell, responsive behavior, and accessibility

- The corpus has its own grouped, collapsible twelve-area rail without replacing the CareerOS application shell.
- The global CareerOS navigation becomes an off-canvas, focus-contained drawer below 900px; the corpus adds a separate mobile area drawer and five-action quick navigation.
- Rail state, explorer preferences, recent searches, disclosure state, and interview notes use scoped local/session keys.
- URL state supports `?view=<key>`, `?record=<id>`, preview mode, direct links, and browser Back/Forward.
- The shell includes skip navigation, semantic navigation/main regions, labeled controls, Arrow/Home/End rail navigation, Escape handling, focus restoration, visible focus states, reduced-motion styles, and non-color-only statuses.
- Automated axe, screen-reader, and contrast audits remain follow-up work; accessibility is not claimed as fully certified.

## Arsenal / CareerOS ownership

| Layer | Responsibility | Added or used here |
| --- | --- | --- |
| Arsenal `@arsenal/ui` | Domain-neutral UI and interaction primitives | `MetricCard`, `ScoreGauge`, `SegmentedControl`, `DisclosureSection`, `StatePanel`; exports, catalog/playground entries, and primitive tests |
| `@career-os/core` | Portable schemas and taxonomies | Versioned resume-corpus schema, provenance/readiness/verification contracts, adapter-facing types |
| `@career-os/ui` | Reusable career-domain presentation | Concern, question, evidence, skill-depth, and empty-state components composed from Arsenal |
| Resume Corpus web feature | Product composition | Twelve views, shell, preview fixtures, search, quality selectors, URL state, API adapter, and responsive styling |

No resume, accomplishment, interviewer, reviewer, or evidence vocabulary was moved into Arsenal. Generic gauges, segmented controls, disclosures, state panels, and metric cards were not duplicated inside CareerOS.

## Data compatibility and truth safety

The live route continues to use `GET/POST/DELETE /accomplishments`, `POST /profile`, and `POST /resume/generate`. `normalizeAccomplishment` maps the legacy payload into `CorpusRecord`; `applyRecordToLegacy` begins from the raw object and writes back fields owned by the new editor. IDs and untouched top-level legacy data are preserved, but unknown fields inside mapped nested collections still need stable-ID merge tests before the adapter can be called fully lossless.

Preview mode is deterministic and local-only. Resume preview generation projects only the selected fixture accomplishments.

Live resume generation now:

- rejects empty or stale accomplishment selections instead of substituting unrelated records;
- returns an explicit 503 when the provider is unavailable instead of fabricating bullets, ATS scores, roles, critiques, or skills;
- accepts only bullets linked to selected source IDs;
- restores company, role, and project identity from the source record;
- filters returned skills to recorded source technologies; and
- labels accepted output as a generated draft with a verification warning.

The inactive legacy accomplishment AI-create/answer endpoints are not called by the canonical workspace. Their provider/fallback path still needs to be replaced and moved behind Arsenal transport before those actions are reintroduced.

## Performance decisions

- Summary, search index, explorer filters, ranking, and graph derivation are memoized.
- Autosave is serialized and debounced at roughly 900ms; undo history is capped at 40 local states.
- The graph is capped at 80 nodes and 120 links and has a list alternative.
- Initial load, search, editor update, graph readiness, and resume-generation timings emit feature performance events.
- The route is still statically imported and client-side searched; it does not yet use pagination, virtualization, or code-split view loading.

## Validation completed

| Check | Result |
| --- | --- |
| `pnpm --filter @career-os/web typecheck` | Passed |
| `pnpm --filter @career-os/web build` | Passed; unrelated static routes log expected API-offline fetch warnings while exiting successfully |
| `pnpm --filter @career-os/web exec playwright test e2e/resume-corpus.spec.ts` | 9/9 passed |
| Resume Corpus E2E coverage | Preview overview and research queue, all 12 URL areas, rail keyboard navigation, universal search/source opening, explorer table switching, all 19 workspace sections, preview autosave persistence, builder/performance mark, four job-match categories, four interview modes with notes/timer persistence, and visible no-overflow 390×844 mobile layout |
| `python -m pytest tests/test_resume_generation.py -q` | 4/4 passed |
| Resume-generation API coverage | Provider failure, source-identity restoration, unlinked-output filtering, invalid selections, and explicit 503 behavior |
| `pnpm --filter @career-os/core test -- --run` | 3/3 passed |
| `pnpm --filter @arsenal/ui typecheck` | Passed |
| Arsenal primitive test | `packages/ui/src/component-foundations.test.ts`: 7/7 passed |
| Browser visual/console QA | Overview, workspace, builder, search, mock interview, graph, and mobile inspected; no console warnings or errors on audited corpus views |

The full API suite currently has one environment-dependent pre-existing Gmail test failure: this machine has a configured sender, while that test expects an unconfigured 503. The Resume Corpus API tests themselves pass.

## Screenshots

- [Overview](screenshots/resume-corpus-overview-final.jpg)
- [Accomplishment workspace](screenshots/resume-corpus-workspace-final.jpg)
- [Resume Builder](screenshots/resume-corpus-builder-final.jpg)
- [Universal search](screenshots/resume-corpus-search-final.jpg)
- [Mock interview](screenshots/resume-corpus-interview-mock-final.jpg)
- [Knowledge Graph](screenshots/resume-corpus-knowledge-graph-final.jpg)
- [Mobile overview — 390×844](screenshots/resume-corpus-mobile-final.png)

## Known limitations

1. The API/database still use the legacy dictionary contract; canonical ownership, revisions, validation, dual-read/write, backfill, pagination, and server-side search remain migration work.
2. Large-corpus behavior remains client-side. There is no list virtualization, server search, or per-view code splitting yet.
3. Settings, templates, match analysis, interview practice state, generated resume output, and preview edits are local/session state unless represented by a legacy record.
4. Builder export is copy/plain text. Drag ordering, PDF/DOCX, page-overflow validation, layout comparison, and a full document engine are not implemented.
5. Job descriptions are analysis inputs, not persisted corpus entities. The derived graph therefore has no durable job-description nodes.
6. The metrics dashboard provides verified rollups and comparisons, not every advanced trend/correlation analysis in the long-form brief. The workspace metric editor remains a compact name/value/status editor.
7. Skills do not claim years, last-used dates, or market demand because the current data has no trustworthy source for them. Timeline zoom/grouping is also not implemented.
8. The research queue is local/derived rather than API-backed. Heatmap and dedicated questions-by-bullet components are not mounted and are not counted as shipped; the active equivalents are the workspace gap map/focus mode and the source-linked interview queue.
9. Legacy inactive tabs and experimental quality components remain in the repository pending parity cleanup.
10. Axe, visual-regression baselines, and explicit large-corpus performance budgets remain follow-up work.

## Success criteria

| User question | Shipped answer |
| --- | --- |
| What accomplishments exist? | Overview plus seven-layout explorer |
| Which stories are strongest? | Readiness/impact ranking and strongest-accomplishment list |
| What is missing? | Workspace readiness summary, gap map, evidence status, and priority actions |
| What will a reviewer challenge? | Review Center plus mapped concern cards |
| Which interview questions are unanswered? | Source-linked filtered question queue and preparation counts |
| Which metrics are proven? | Verification-aware metrics dashboard and linked evidence |
| Which accomplishments are ready for a target resume? | Builder readiness indicators, ranking, and source selection |
| What should improve next? | Overview priority actions and focused gap resolution |

The primary criterion is met: the corpus behaves as a progressive-disclosure career knowledge system rather than a flat resume-bullet editor.
