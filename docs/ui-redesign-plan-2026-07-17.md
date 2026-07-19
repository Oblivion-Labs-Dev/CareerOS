# CareerOS UI/UX redesign architecture plan

**Prepared:** 2026-07-17  
**Source audit:** [product-audit-2026-07-17.md](./product-audit-2026-07-17.md)

## Product model

CareerOS will be organized around a continuous, non-punitive loop:

1. **Focus** — choose the highest-impact action today.
2. **Strengthen** — improve resume evidence and reusable career stories.
3. **Discover** — evaluate saved roles and decide where to invest.
4. **Apply** — move opportunities through an accurate pipeline.
5. **Connect** — build referral and recruiter context around target companies.
6. **Prepare** — enter interviews with source-linked proof and a stage-specific plan.
7. **Review** — learn from activity, conversion, and evidence progress.

The navigation will expose tasks, not internal modules. Existing URLs remain stable.

## Proposed information architecture

| Navigation group | Visible destination | Stable route | Responsibility |
| --- | --- | --- | --- |
| Today | Command Center | `/dashboard` | Priorities, follow-ups, evidence gaps, interview prep, and weekly pulse |
| Career foundation | Profile | `/profile` | Identity, targets, answer bank, and setup readiness |
| Career foundation | Documents | `/resumes` | Resume library, generated drafts, and evidence-source handoff |
| Strengthen | Resume Intelligence | `/resume-corpus` | Accomplishments, evidence, builder, match, and detailed prep |
| Search & apply | Opportunities | `/jobs` | Saved roles, evaluation, comparison, and ApplyPilot handoff |
| Search & apply | Applications | `/applications` | Pipeline, follow-ups, detail, and status updates |
| Connect | Relationships | `/networking` | Referrals, recruiter activity, and company relationship context |
| Prepare | Interviews | `/interviews` | Opportunity-level prep queue and entry into corpus practice |
| Review | Progress & Insights | `/analytics` | Funnel, activity, source mix, follow-through, and explanations |
| Tools | ApplyPilot | `/apply-pilot` | Browser extension setup and health |
| Tools | Resources | `/apply/job-search-guide` | Curated job-search guidance |
| System | Settings | `/settings` | Real preferences and transparent unavailable controls |
| System | Roadmap | `/roadmap` | Product-development status |

`/referrals` and `/apply/outreach` remain stable deep routes and are linked from Relationships. Legacy aliases continue to redirect.

## Route changes

- Replace the `/dashboard` redirect with the Command Center.
- Preserve all existing route paths and redirects.
- Add query-state patterns where they improve shareability: application view/filter/detail, job selection, and relationship section.
- Link `/interviews` into `/resume-corpus?view=interview&record=<id>` when source evidence is available.
- Compact the global rail whenever `#corpus-main` is present so the corpus remains the dominant workspace.

## Design system

### Foundations

- Keep Arsenal color primitives and light/dark theme behavior.
- Introduce CareerOS semantic tokens for canvas, panel, text, border, accent, info, success, warning, danger, and data-series colors.
- Use Inter for body/UI and Outfit only for high-level display text; reduce oversized headings.
- Adopt a 4px base spacing rhythm with named layout intervals and 12/16/20/28px panel padding.
- Use three elevation levels: border-only, raised workspace, and temporary overlay. Avoid broad glassmorphism.
- Motion defaults: 180ms for controls, 220ms for panels, no auto-advancing content, and full reduced-motion overrides.

### Shared product components

- App rail with recognizable inline SVG icons, grouped navigation, compact corpus mode, backend status, and mobile drawer.
- Workspace header with title, context, global search, primary action, and optional view controls.
- Action card with priority reason, source, impact, and one direct action.
- Metric card with comparison/explanation slot and explicit empty state.
- Status badge that always includes text or iconography, never color alone.
- Filter/command bar with mobile sheet behavior.
- Empty/error/offline state with separate “no data” and “service unavailable” language.
- Timeline and activity item with date, status, and next action.
- Accessible chart frame with title, summary, legend, table/list fallback, and source note.
- Application board/list and detail drawer.
- Command palette for navigation and direct workflow entry.

## Command Center rules

The Command Center will use deterministic actions only:

1. Overdue or due-today application follow-up.
2. Active interview-stage preparation.
3. Resume accomplishment with missing or weak evidence.
4. Submitted application without a follow-up date.
5. Saved job not yet moved into the application pipeline.
6. Incomplete profile/document foundation.

Each recommendation will show why it appears and link to the exact workflow. If no action can be derived, the empty state offers setup choices rather than inventing a personalized plan.

The initial weekly pulse will be derived from stored application timestamps and corpus readiness. It will not claim goals, streaks, or trend history that the data cannot support.

## Workflow redesigns

### Resume and evidence

- Preserve the existing twelve corpus views, compatibility adapter, autosave, truth-safety behavior, and test suite.
- Add Command Center deep links into exact accomplishment records and focused gaps.
- Reduce global shell width on the corpus route.
- Present Documents as an output library/handoff, not a second evidence editor.

### Applications

- Add board and list views over the same application array.
- Add filtering by status, company/role text, follow-up state, and source/platform.
- Add an accessible detail drawer with dates, notes, posting link, resume/cover-letter references, and status controls.
- Use existing `PATCH /applications/{id}` for non-destructive status/follow-up edits.
- Provide explicit empty, loading, offline, update-success, and update-error states.

### Jobs

- Add search, evaluation cues, source/platform metadata, and saved-date ordering.
- Keep job discovery external and ApplyPilot-based; do not imply CareerOS has a search index.
- Support side-by-side comparison only for fields that exist in stored records.
- Deep-link selected jobs into Resume Corpus job match by user-controlled description paste/handoff until a durable job-description contract exists.

### Relationships

- Make `/networking` the overview of referrals and outreach health.
- Preserve `/referrals` as the full editable referral table/form.
- Preserve `/apply/outreach` as campaign delivery detail.
- Do not send email or mutate contacts from the overview without an explicit user action.

### Interviews

- Derive the prep queue from applications in `interviewing` or later active stages.
- Link preparation to source evidence in Resume Corpus.
- Show stage, recency, missing notes/follow-up, and a clear next action.
- Keep practice timers and notes local where the current corpus contract does so; label that state honestly.

### Progress and gamification

- Show application funnel, weekly activity, follow-up health, source/platform mix, and evidence readiness using real stored data.
- Use mature milestones: evidence-backed story completed, interview prep coverage improved, follow-up completed, and pipeline stage advanced.
- No daily punishment, countdown urgency, confetti by default, or opaque composite “career score.”
- Any readiness percentage must expose its calculation and underlying sources.

## API and data contracts

No database or API migration is required for this UI phase. Stable reads and mutations are documented in the audit.

Client-derived view models will normalize optional legacy fields at the boundary:

- application: identity, company, role, status, location, platform/source, URL, timestamps, follow-up, notes, and document references;
- job: identity, company, title, description, URL, location, platform, and saved timestamp;
- accomplishment summary: identity, title/company/role, readiness, evidence/metric/question counts, and last update;
- referral: identity, contact/company/context/status, and follow-up metadata.

Unknown fields remain untouched. Mutations send narrow patches rather than replacing records.

## Dependency decision

No new dependency is required for the first redesign phase.

- Inline SVG icons avoid adding an icon package for a small, stable navigation set.
- CSS/SVG funnel, bar, and activity visualizations are sufficient for current dataset sizes and keep the initial bundle small.
- Existing React, Next.js, Framer Motion, Arsenal UI, and CareerOS UI cover the required interaction primitives.

A chart library should be reconsidered only if zooming, brushing, dense time series, or cross-filtering becomes a tested requirement.

## Controlled implementation phases

### Phase 1 — system and shell

- Add semantic CareerOS tokens and a scoped component stylesheet.
- Rebuild visible navigation around the new information architecture.
- Add real icons, compact corpus mode, skip navigation, global command palette, and mobile behavior.
- Validate all existing routes and Resume Corpus navigation before continuing.

### Phase 2 — Command Center and shared components

- Build typed view-model/derivation helpers.
- Build action, metric, timeline, chart-frame, state, and workspace-header components.
- Replace `/dashboard` redirect with a real, data-derived page.
- Add tests for empty/offline/real-data action prioritization.

### Phase 3 — core operational workspaces

- Redesign Applications with board/list, filters, detail, and narrow mutations.
- Redesign Jobs with evaluation and comparison affordances.
- Connect Documents to Resume Corpus and existing document data.
- Validate desktop, tablet, and mobile after each route.

### Phase 4 — connect, prepare, and review

- Rebuild Networking as the relationship overview.
- Rebuild Interviews as the opportunity prep queue.
- Rebuild Analytics as Progress & Insights with accessible data-derived visualizations.
- Keep deep CRUD and campaign pages stable.

### Phase 5 — refinement and validation

- Separate no-data, offline, loading, success, and error states.
- Audit keyboard order, focus restoration, labels, contrast, reduced motion, touch targets, and 200% zoom.
- Add Playwright coverage for Command Center, navigation, Applications, and mobile layouts.
- Run typecheck, unit tests, API tests, E2E tests, and production build.
- Inspect 1440px, 1024px, 768px, and 390px layouts with empty and realistic data.

## Migration risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Overwriting current user-owned Resume Corpus and outreach work | Inspect current diffs before overlapping edits; prefer new files and narrow patches. |
| Conflating offline with empty | Carry explicit availability state and retain the backend status control. |
| Legacy application/job shapes | Normalize optional aliases in view-model helpers; patch only changed fields. |
| Nested corpus chrome becomes cramped | Compact the global rail through route-presence styling; do not rewrite corpus internals. |
| Client bundle growth | Avoid new chart/icon dependencies and lazy-load drawers/palettes where useful. |
| False personalization | Derive every action/metric from stored data and show the reason/source. |
| Breaking extension sync | Do not alter `/api/db`, extension schemas, or database layout. |
| Accessibility regression | Preserve semantic landmarks and add keyboard/mobile Playwright coverage before removing old UI. |

## Validation gates

After each phase:

1. `pnpm --filter @career-os/web typecheck`
2. Relevant Playwright specs
3. Manual desktop and 390px inspection
4. Keyboard navigation and focus check
5. Empty and backend-offline state check
6. Current Resume Corpus preview smoke test

Final gate:

- full workspace typecheck and build;
- core and extension tests;
- API tests, with environment-dependent Gmail behavior reported separately;
- all web E2E tests;
- production screenshot inspection across the primary navigation;
- no horizontal overflow, clipped controls, or inaccessible chart-only information;
- documentation updated with implemented scope, dependencies, validation, limitations, and next steps.

