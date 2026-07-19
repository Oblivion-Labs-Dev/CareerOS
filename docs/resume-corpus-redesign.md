# Resume Corpus redesign

## Status and intent

The redesign is implemented as a UI-first compatibility slice at `/resume-corpus`. See **`docs/resume-corpus-completion-report.md`** for the full completion report (what shipped, what remains, success criteria).

The canonical entry point is the small server wrapper in `apps/web/app/(app)/resume-corpus/page.tsx`, which validates initial query state and renders `resume-corpus-client.tsx`. The client owns orchestration; individual views remain independently replaceable.

The current slice deliberately reads and writes the existing accomplishment API. A versioned domain schema and a loss-preserving adapter seam are in place, but the API and database have not yet moved to the canonical model. The migration below distinguishes implemented behavior from the remaining cutover work.

## Audit baseline

The previous corpus experience combined a large legacy JSON shape, many local tabs, and application orchestration in one client surface. The audit found:

- no durable URL state for the active area or selected accomplishment;
- arbitrary JSON persistence through `EntityStore`, with no corpus/user scope, canonical validation, revision control, pagination, or server-side search;
- generated, inferred, imported, and user-entered facts represented alike, making truth and evidence status unclear;
- local-only or simulated secondary workflows, including matching, research, and interview state;
- duplicated generic UI and OpenRouter transport concerns that belong in Arsenal;
- inaccessible clickable containers, weak dialog/focus behavior, fixed dark colors, a second nested sidebar, and an unbounded graph pattern; and
- an unsafe LLM fallback that can invent companies, scale, latency, and cost claims when generation fails.

The redesign separates generic UI, CareerOS domain semantics, route orchestration, and persistence. It also makes readiness, provenance, evidence, unanswered questions, and reviewer concerns visible instead of presenting every record as equally complete.

## Information architecture and route/component map

All primary areas share `/resume-corpus` and are deep-linked with `?view=<key>`. A selected accomplishment adds `&record=<id>`. This keeps one corpus workspace while making browser history and direct links useful.

| View key | Primary component | Responsibility |
| --- | --- | --- |
| `overview` | `components/corpus-overview.tsx` | Profile context, corpus health, readiness, coverage, and priority actions |
| `accomplishments` | `components/accomplishment-explorer.tsx` / `components/accomplishment-workspace.tsx` | Multi-view discovery plus focused, editable story workspace |
| `builder` | `components/corpus-resume-builder.tsx` | Select evidence-backed stories and generate role-targeted resume bullets |
| `match` | `components/corpus-job-match.tsx` | Compare corpus evidence with a target role and expose coverage gaps |
| `interview` | `components/corpus-interview-prep.tsx` | Prepare and practice linked interview questions and answers |
| `metrics` | `components/corpus-metrics-dashboard.tsx` | Inspect metrics, verification, and missing measurement coverage |
| `skills` | `components/corpus-skills-map.tsx` | Derive skill depth from linked accomplishments rather than flat tags |
| `graph` | `components/corpus-knowledge-graph.tsx` | Explore bounded relationships with an accessible list alternative |
| `evidence` | `components/corpus-evidence-vault.tsx` | Inspect artifacts, URLs, provenance, and evidence gaps |
| `reviews` | `components/corpus-review-center.tsx` | Triage reviewer concerns by severity and resolution state |
| `templates` | `components/corpus-templates.tsx` | Browse reusable output structures without coupling them to the shell |
| `settings` | `components/corpus-settings.tsx` | Configure corpus profile and experience preferences |

Supporting composition is intentionally narrow:

- `page.tsx` parses `view`, `record`, and `preview` on the server.
- `resume-corpus-client.tsx` loads data, owns navigation and selection, connects API actions, computes summaries/search, and selects a view.
- `components/corpus-secondary-views.tsx` adapts the ten secondary views to a small shared record-selection contract.
- `components/corpus-shell.tsx` provides the grouped desktop rail, mobile drawer/quick navigation, status, search, theme, and create actions.
- `corpus-model.ts` contains the legacy adapter, derived selectors, summary, and search index. `corpus-fixtures.ts` contains preview-only data.
- `resume-corpus.module.css` owns responsive layout and feature-specific presentation using shared tokens.

The older `*-tab.tsx` implementations are not in the canonical import path. They should remain only until parity review is complete, then be removed.

## Arsenal and CareerOS ownership

Arsenal remains the shared library; CareerOS owns career meaning and product workflows.

| Layer | Owns | Examples in this redesign |
| --- | --- | --- |
| Arsenal `@arsenal/ui` | Domain-neutral primitives, tokens, interaction behavior, motion, and accessibility defaults | `MetricCard`, `ScoreGauge`, `SegmentedControl`, `DisclosureSection`, `StatePanel`, badges, buttons, tooltips |
| Arsenal backend | Provider-neutral LLM transport, retries, logging, and structured response validation | `OpenRouterClient` target integration |
| CareerOS `@career-os/core` | Portable career schemas, enums, validation, and selectors with no React dependency | `careerAccomplishmentSchema`, provenance/readiness/verification schemas, corpus taxonomy |
| CareerOS `@career-os/ui` | Reusable career-domain presentation composed from Arsenal primitives | `ReadinessBadge`, `ConcernCard`, `EvidenceViewer`, `InterviewQuestionCard`, `SkillDepthIndicator` |
| CareerOS web feature | Route state, data adapters, fixtures, product copy, feature composition, and API calls | `/resume-corpus`, explorer/workspace, search, all twelve views |
| CareerOS API | Authorization, validated contracts, persistence, revisions, search/pagination, and AI workflow policy | Current accomplishment and resume endpoints; canonical v1 API is follow-up |

No accomplishment, resume, reviewer, interview, or evidence vocabulary should move into Arsenal. Conversely, generic cards, gauges, disclosures, state panels, keyboard behavior, and provider transport should not be copied into CareerOS.

## Canonical schema and provenance

`packages/career-core/src/schemas/resume-corpus.ts` defines the target v1 model:

- `schemaVersion: 1` and non-negative `revision` make migrations and optimistic concurrency explicit;
- optional `personId` and `corpusId` provide the future ownership boundary;
- readiness is `draft`, `needs-input`, `review`, or `ready`;
- metrics carry confidence, verification, source, scope, time period, and related accomplishment IDs;
- evidence, reviewer concerns, interview questions, and resume variants have stable IDs and lifecycle state;
- facts use `manual`, `imported`, `generated`, or `inferred` provenance; and
- `.passthrough()` preserves migration-only fields that the v1 client does not yet understand.

Generated content is never equivalent to verified evidence. A generated or inferred metric remains unverified until the user supplies a source or explicitly confirms it. Future generation APIs must return provenance and warnings with the content, not silently promote claims to facts.

## Legacy adapter and dual-read migration

The implemented compatibility path is:

```text
GET /accomplishments
  -> normalizeAccomplishment(legacy)
  -> CorpusRecord + exact legacy payload in CorpusRecord.raw
  -> redesigned views

edited CorpusRecord
  -> applyRecordToLegacy(record), starting from raw
  -> POST /accomplishments
  -> normalize saved legacy response
```

`normalizeAccomplishment` derives the new view model without mutating the source. `applyRecordToLegacy` begins with `...raw`, deep-spreads the mapped legacy objects, and overwrites only fields supported by the new editor. New records are created through `createLegacyAccomplishmentDraft`, so they remain usable by existing consumers. This preserves IDs and untouched legacy fields during the UI migration. Adapter tests must additionally prove stable-ID merging for mapped collections before the path is described as fully lossless for every unknown nested field.

The API dual-read/dual-write cutover should proceed as follows:

1. Publish the v1 contract as the single source for TypeScript and Python validation. Reject invalid readiness, provenance, relationship, and score values at the API boundary.
2. On reads, parse `schemaVersion === 1` as canonical. For an unversioned record, run the legacy adapter and retain the original payload as migration metadata. Return an explicit schema version and revision.
3. On writes, require the caller's last-seen revision, write canonical v1, increment the revision, and temporarily retain a legacy projection/snapshot for rollback. Reconcile record counts, IDs, timestamps, and field checksums.
4. Backfill existing rows in batches. Quarantine validation failures without deleting or replacing the source JSON; produce an operator-readable migration report.
5. Switch the UI to canonical reads after parity metrics are clean. Keep the legacy adapter and export for one release window, then remove dual-write and the unused tab implementation.

Lossless migration invariants are: never change a record ID, never discard an unknown field, never convert generated text into manual provenance, never mark an unverified metric verified, and never advance a revision without a durable write.

## URL, local, and draft state

The server wrapper validates initial query values. The client uses `history.pushState`/`replaceState` and a `popstate` listener so Back/Forward restores the view and selected record without a reload. Examples:

- `/resume-corpus`
- `/resume-corpus?view=metrics`
- `/resume-corpus?view=accomplishments&record=<id>`
- `/resume-corpus?preview=1&view=reviews`

Shareable state belongs in the URL. Device preferences stay local: rail collapse uses `careeros:corpus:rail-collapsed`, explorer display/filter preferences use `careeros:corpus:explorer`, recent searches use `careeros:corpus:recent-searches`, and disclosure state uses `careeros:corpus:sections:<recordId>`. The editor keeps a maximum of 40 undo states in memory, autosaves after 900 ms, protects unsaved navigation with `beforeunload`, and exposes saved/unsaved/saving/error state. That history is session-local, not a durable record revision log.

## Preview fixtures

`?preview=1` loads the fictional Alex Morgan profile and four fictional accomplishments from `corpus-fixtures.ts`. The fixture set intentionally covers ready/review/needs-input states, verified and missing evidence, metrics, concerns, questions, and resume variants; links use `example.com`.

Preview mode bypasses the profile and accomplishment fetch. Create, edit, delete, and resume generation branches update in-memory fixture state only and do not call the API. Refreshing resets the fixture. The shell labels the mode as preview/local data so it cannot be confused with a persisted career record.

## Accessibility and performance decisions

- The shell exposes a skip link, semantic navigation/main regions, `aria-current`, labeled controls, and desktop Arrow/Home/End navigation. Mobile has a drawer and a five-action quick navigation bar.
- Search is available with Ctrl/Cmd+K. Dialogs use `role="dialog"`, `aria-modal`, initial focus, focus containment, Escape handling, and focus restoration.
- Interactive rows are buttons rather than clickable `div` elements. Save and error state uses live/alert semantics; disclosures expose expanded state.
- Feature CSS uses CareerOS/Arsenal variables, visible `:focus-visible` styles, light/dark compatibility, breakpoints at 1260/1020/760/420 px, and a reduced-motion override.
- Summary, search index, filters, and graph derivation are memoized. The graph uses deterministic coordinates, caps output at 80 nodes/120 links, and offers a searchable list view instead of running an endless force simulation.
- Loading, empty, and error states are explicit and do not clear already stored data when the API is unavailable.

## Preserved functionality

The redesigned route actively preserves existing list, create, update/autosave, delete, and resume-generation behavior through `GET/POST/DELETE /accomplishments` and `POST /resume/generate`. The resume endpoint now rejects empty or stale selections, returns an explicit 503 when its provider is unavailable, filters output to selected source IDs, restores company/role/project metadata from those sources, and labels accepted output as a generated draft with a verification warning. It never substitutes unrelated records or fabricates a fallback result. Existing legacy records remain editable because the raw payload is carried through the adapter. Explorer views, filtering, universal search, readiness/coverage summaries, metrics, evidence, reviews, interview questions, skills, graph relationships, templates, and settings are separated into focused components.

`POST /accomplishments/ai-generate` and `POST /accomplishments/{id}/answer-question` remain available in the API, but the canonical create/workspace flow does not currently call them. AI structuring should be reintroduced only after truth-safe fallback behavior, explicit provenance, and the Arsenal transport boundary are enforced.

## Rollout plan

1. Keep the redesigned route available in fixture preview and verify every view at supported breakpoints.
2. Stabilize Arsenal primitives first; consume them through `@arsenal/ui` and prohibit CareerOS copies.
3. Lock the v1 schema and adapter with validation and round-trip fixtures, including malformed and unknown legacy fields.
4. Add scoped, validated, paginated canonical API reads and revision-aware writes behind a feature flag.
5. Run dual-read/dual-write plus a dry-run backfill; compare IDs, counts, checksums, provenance, evidence status, and generated warnings.
6. Enable canonical storage for an internal cohort, monitor conflicts/errors and adapter fallbacks, then expand gradually.
7. After one rollback window with no legacy-only reads, remove dual-write, legacy tabs, and duplicated CareerOS primitives. Retain a read-only legacy export and migration report.

## Known limitations

- The API still accepts `accomplishment: dict[str, Any]`; it does not enforce the v1 schema, corpus/user ownership, provenance rules, or revision conflicts.
- `GET /accomplishments` returns the full corpus. Pagination, server-side filtering/search, and large-list virtualization remain follow-up work.
- Core accomplishment CRUD persists, but settings, templates, match analysis, interview practice state, generated resume output, and preview changes are currently local/session state unless represented in the legacy record.
- `revision` exists in the core schema only. The 40-state editor history is not durable version history and cannot restore a prior server revision.
- The UI is still a legacy read/write client; API dual-read, dual-write, backfill, and canonical persistence are not implemented yet.
- The legacy adapter preserves raw data by default, but mapped arrays need stable-ID merge and round-trip coverage to guarantee preservation of unknown nested collection fields.
- The inactive accomplishment AI-create/answer endpoints still use legacy Python provider/fallback behavior and remain intentionally disconnected from the canonical create/workspace flow. Resume generation no longer has a synthetic fallback, but provider transport still belongs in Arsenal and generated bullet text still requires user verification against linked evidence.
- Search and graph computation are client-side. The graph is intentionally bounded and is not yet a persisted semantic graph.
- Legacy tab files remain in the tree during parity review even though the canonical route no longer imports them.

## Validation plan

| Layer | Current coverage | Required before canonical cutover |
| --- | --- | --- |
| Arsenal UI | Primitive typecheck/unit catalog | Keyboard/focus, controlled state, reduced-motion, and light/dark tests for every shared primitive |
| Career core | Schema default/passthrough and invalid metric/concern tests | Full v1 fixtures, provenance rules, relationship integrity, revision rules, and legacy round-trip/property tests |
| Web | Playwright preview overview, all 12 URL areas, rail keyboard navigation, Ctrl/Cmd+K search, seven-view explorer/table switch, 19-section workspace, preview autosave, builder, job-match classes, interview state, and mobile overflow | Live CRUD/error recovery, URL Back/Forward, all filter combinations, axe, visual baselines, and proof that preview makes no corpus API calls |
| Accessibility | Semantic/focus behavior implemented | Automated axe scans plus keyboard-only, screen-reader, contrast, zoom, and reduced-motion review in both themes |
| API/migration | Resume generation tests cover provider failure, source identity, invalid selection, and explicit 503 behavior | Canonical contract, authorization/scope, cursor pagination, optimistic concurrency, dual-read/write, idempotent backfill, quarantine, and rollback tests |
| Performance | Memoization and graph bounds implemented | Profile with 1k/10k records; measure load, search, filter, editor interaction, memory, and graph/list rendering budgets |

Representative checks:

```powershell
pnpm --filter @career-os/core test
pnpm --filter @career-os/core typecheck
pnpm --filter @career-os/ui typecheck
pnpm --filter @career-os/web typecheck
pnpm --filter @career-os/web exec playwright test e2e/resume-corpus.spec.ts
python -m pytest apps/api/tests -q
pnpm --dir ../Arsenal --filter @arsenal/ui test
pnpm --dir ../Arsenal --filter @arsenal/ui typecheck
```

Cutover requires all contract and migration tests to pass, zero unexplained record/checksum differences, no fabricated fallback content, and successful keyboard/visual review of all twelve areas.
