# CareerOS product and repository audit

**Audited:** 2026-07-17  
**Scope:** `apps/web`, `apps/api`, `apps/extension`, `packages/career-core`, and `packages/career-ui`  
**Baseline:** local Next.js application, rendered at 1440x1000 and 390x844; API and source contracts inspected directly

## Executive assessment

CareerOS has a credible working core, but the product currently exposes its implementation history more clearly than its career workflow. ApplyPilot, the application tracker, referrals, recruiter outreach, and the new Resume Corpus all have real data paths. The remaining primary destinations are a mix of read-only summaries, redirects, and explanatory scaffolds. The strongest existing product is the Resume Corpus, but it introduces a second twelve-area navigation rail inside the global eighteen-item navigation, creating excessive choice and a cramped working area.

The redesign should preserve route compatibility and API payloads while reorganizing the experience around the user's loop:

> Focus -> Strengthen -> Discover -> Apply -> Connect -> Prepare -> Review

The highest-value change is a real Command Center at `/dashboard`: it should derive next actions from stored applications, jobs, profile data, and accomplishment evidence. It must not invent goals, readiness, or activity. The second priority is consolidating the global navigation and turning the tracker, jobs, contacts, interview, and insights pages into connected workspaces instead of disconnected descriptions.

## Repository map

| Layer | Current implementation | Assessment |
| --- | --- | --- |
| Web | Next.js 15 App Router, React 19, server and client components | Sound base. Page composition is inconsistent and several routes are scaffolds. |
| Styling | Tailwind 3 for package content, Arsenal tokens, and a 3,600+ line global stylesheet | Good tokens and a distinct dark visual seed; global CSS has accumulated route-specific systems and is difficult to govern. |
| Motion | Framer Motion and `react-intersection-observer` | Available and used selectively. Reduced-motion handling exists in the corpus. |
| Shared UI | Arsenal primitives plus a small `@career-os/ui` package | Correct ownership boundary. CareerOS-wide workflow components are still missing. |
| State | Server fetches, isolated React state, URL state in the corpus, local/session storage for device and draft state | Appropriate for the current scale, but no shared query cache or consistent mutation/error layer. |
| API | FastAPI with REST endpoints and legacy `/api/db` sync | Working local-first service. Several payloads remain unvalidated dictionaries. |
| Persistence | SQLAlchemy `KVStore` and generic JSON `EntityStore`; SQLite by default | Flexible for migration, but lacks ownership, relational integrity, revisions, pagination, and production authorization. |
| Authentication | No user authentication; API key guards only selected sensitive actions outside dev mode | Suitable only for local/single-user operation. Must be explicit in product copy and deployment guidance. |
| Feature flags | No general flag system; dev mode, extension URLs, and local corpus coming-soon metadata act as configuration gates | Add flags only when a real rollout requires them; do not introduce a framework for its own sake. |
| Analytics | `career_event` writes, tracker counts, corpus performance marks | Events are stored but not exposed through a dedicated read contract; monitoring is minimal. |
| Tests | Playwright site health and extensive Resume Corpus preview tests; API unit tests; core schema tests | Strong corpus coverage, thin coverage for the rest of the product and no accessibility automation. |
| Extension | ApplyPilot MV3 Chrome/Firefox build with autofill, learning, sync, tracking, and browser packaging | Working product surface, but it has a separate UI and test surface outside this web redesign. |

## Route and feature audit

Status definitions: **Complete** means the reachable workflow and its data path work for the stated scope; **Partial** means a useful slice works but important actions or states are absent; **Placeholder** means the page mostly explains a future workflow; **Alias** means it intentionally redirects.

| Feature | Route | Components / data source | Status | UX and technical findings | Action |
| --- | --- | --- | --- | --- | --- |
| Marketing landing | `/` | `LandingPage`, extension store metadata | Complete | Strong visual identity but disconnected from the in-product workflow language. | Improve copy and preserve. |
| Command Center | `/dashboard` | Redirects to `/applications` | Missing | No answer to “what should I do today?” and no cross-workflow prioritization. | Rebuild as a real, data-derived workspace. |
| Application tracker | `/applications` | `/tracker/summary`, `ApplicationTrackerRefresh` | Partial | Real records and counts render, but the page is mostly a read-only report; no pipeline manipulation, filters, detail panel, or clear empty-state route into setup. Response-rate calculation excludes later-stage applications from its denominator logic. | Redesign around a board/list, detail drawer, follow-ups, and stable API fields. |
| Saved jobs | `/jobs` | `GET /jobs` | Partial | Real saved jobs render, but there is no internal evaluation, fit state, comparison, sorting, or job detail workspace. | Redesign; preserve capture through ApplyPilot. |
| Profile | `/profile` | `GET /profile` | Partial | Useful inspection of real profile JSON but largely read-only and framed around backend internals. Editing exists elsewhere in corpus settings. | Consolidate profile editing and readiness; keep `/profile`. |
| Documents | `/resumes` | `WorkflowPage`; existing resume APIs and Resume Corpus builder are not integrated | Placeholder / duplicated | “Documents,” “Resume Corpus,” and cover-letter aliases overlap without a clear hierarchy. | Redesign as a document hub; make Resume Corpus the evidence source. |
| Resume Corpus | `/resume-corpus` | Twelve-area feature, legacy adapter, accomplishment/profile/resume APIs | Complete UI slice; partial canonical persistence | Strongest workflow: search, explorer, editor, evidence, metrics, job match, interview prep, builder, URL state, autosave, and preview. Nested full navigation competes with the global shell. Canonical schema is not enforced by API; large corpus remains client-side. | Preserve business logic and views; improve shell integration and defer canonical storage migration. |
| Resume evidence collection | `/resume-corpus?view=accomplishments` and record workspace | Legacy accomplishment CRUD via compatibility adapter | Complete UI slice | Detailed evidence/readiness model and error states exist. Unknown nested legacy fields still need stable-ID merge proof. | Preserve; expose focused entry points from Command Center. |
| Resume generation | `/resume-corpus?view=builder` | `POST /resume/generate` | Complete guarded slice | Source-linked and truth-safe; export remains text/copy only and generated drafts are not durable. | Improve handoff and document hub integration; preserve contract. |
| Resume/job match | `/resume-corpus?view=match` | Client-side analysis of supplied description and corpus | Complete local slice | Evidence categories are honest and useful; job descriptions are not persisted. | Preserve; add handoff from saved jobs without inventing persistence. |
| Interview preparation | `/resume-corpus?view=interview` | Corpus questions and local practice state | Complete local slice | Good four-mode experience, but the global `/interviews` route duplicates the concept and is only a scaffold. | Make `/interviews` the opportunity-level launchpad into corpus prep. |
| ApplyPilot installer and one-off email | `/apply-pilot` | Extension metadata/download, Gmail verify/send/thread APIs | Complete for local MVP | Installation, autofill capability, email composition, and backend dependence are mixed on one long page. | Improve hierarchy; keep the working actions. |
| Recruiter outreach campaigns | `/apply/outreach` | `GET /email/outreach-campaigns` | Complete read dashboard | Useful delivery/bounce information. Campaign creation remains script-driven and external to the UI. | Preserve; position under Connect rather than Apply. |
| Referrals | `/referrals` | Referral CRUD and ask-message endpoints | Complete local MVP | Real create/update/delete and message copy. Separate from “Contacts,” so relationship context is fragmented. | Consolidate visually with networking while preserving route and CRUD. |
| Contacts / networking | `/networking` | `WorkflowPage` only | Placeholder | Describes recruiters, contacts, and companies without showing stored referrals or conversations. | Rebuild as a relationship workspace fed by existing referral and outreach data. |
| Analytics | `/analytics` | `WorkflowPage` only | Placeholder | No funnel or activity visualization despite sufficient application timestamps/status/source fields for a truthful first version. | Rebuild as Progress & Insights with derived, accessible charts. |
| Job-search guide | `/apply/job-search-guide` | Static curated guide and tool catalog | Complete content feature | Dense and useful, but reads like a separate microsite and is over-prominent in primary navigation. | Preserve as a contextual resource, not a primary daily destination. |
| Roadmap | `/roadmap` | `@career-os/core` roadmap data | Complete informational page | Useful for developers/product planning, but not a core end-user career workflow. | Move to secondary/system navigation. |
| Settings | `/settings` | `WorkflowPage` only | Placeholder | Privacy, sync, export, deletion, and preferences are described but not implemented. | Clearly label unavailable actions and keep only real controls. |
| Legacy aliases | `/features`, `/autofill`, `/cover-letters`, `/job-search-portals`, `/apply/resume-tools`, `/recruiters` | Next redirects | Alias | Route compatibility is useful; aliases should not appear as separate product features. | Preserve redirects, remove duplication from information architecture. |
| Privacy policy | `/privacy/applypilot` | Static policy | Complete | Required public support content. | Preserve. |

## Main journey audit

| Journey | Current path | Finding | Required change |
| --- | --- | --- | --- |
| Onboarding | Landing -> ApplyPilot installer -> Profile | No guided in-product sequence, progress, or completion state. | Add a dismissible, user-controlled setup path derived from actual profile/resume/extension readiness. |
| Resume import | ApplyPilot/API parser -> profile/documents | Parser and document endpoints exist, but the web document route does not expose a coherent import workflow. | Connect Documents to existing API capabilities; do not fabricate upload persistence. |
| Resume analysis | Resume Corpus | Strong evidence/readiness analysis exists. | Surface it as “Strengthen” and link priority gaps into exact records. |
| Bullet evidence | Resume Corpus accomplishment workspace | Strong, complete UI-first slice. | Preserve and use its statuses in cross-product next actions. |
| Interview preparation | Global scaffold plus complete corpus feature | Duplicate concepts with no opportunity handoff. | Use `/interviews` as the opportunity/stage selector; deep-link to source evidence. |
| Job discovery | ApplyPilot capture plus static guide | Capture works, discovery is external and the saved-job page is thin. | Make saved roles evaluable and keep external discovery resources contextual. |
| Application tracking | Tracker summary | Data exists, but no operational board or detail editing. | Add status workflow, follow-up queue, filters, and record detail. |
| Referrals and networking | Referrals CRUD, outreach campaigns, contacts scaffold | Working data is split across three destinations. | Unify under Connect with segmented views and stable old routes. |
| Follow-ups | `nextFollowUpAt` and outreach results | Due counts exist, but no central queue/timeline. | Add a date-aware queue in Command Center and Applications. |
| Progress review | No working global view | Career events and application timestamps are sufficient for a basic truthful review. | Add weekly activity/funnel/source views with explicit data-source explanations. |

## Navigation and organization findings

- The global navigation exposes eighteen items across implementation-centric groups; Roadmap is the only “Overview” item while the real dashboard is hidden behind a redirect.
- Foundation mixes identity, relationships, documents, evidence, and settings. Apply mixes a browser extension, email campaign reporting, application tracking, saved jobs, and a static guide.
- The same concepts appear under multiple names: Documents / Resumes / Cover Letters / Resume Corpus; Contacts / Referrals / Recruiters / Outreach; Dashboard / Applications.
- Redirect aliases are correctly kept for compatibility but should not influence the visible product map.
- Resume Corpus adds twelve more destinations inside the page. On desktop this produces two full sidebars; on mobile it produces two drawers plus quick navigation.
- Backend status is repeated in the sidebar and as a large banner, consuming the first mobile viewport before the user sees their work.
- Primary navigation icons are letter abbreviations, which are difficult to scan and visually noisy.

## State, accessibility, responsiveness, and performance

### State handling

- Resume Corpus has explicit loading, error, empty, saved, unsaved, and preview states.
- Most other pages catch API errors and convert them into empty data, which makes “offline” indistinguishable from “no records” without the separate backend banner.
- Application and job server pages have no shared retry/error contract.
- The product has no general offline mode; local draft recovery exists only in Resume Corpus.

### Accessibility

- Positive: semantic landmarks, focus trapping, Escape behavior, visible focus styles, reduced-motion support, and keyboard navigation are implemented in the corpus and mobile sidebar.
- Gaps: no automated axe coverage, charts outside the corpus are absent, letter icons have weak semantic affordance, and some global status/error presentation is verbose on small screens.
- Required: WCAG 2.2 AA contrast review in both themes, keyboard tests for the new command palette and drawers, non-color status labels, and text summaries for every visualization.

### Responsive behavior

- The global sidebar becomes an accessible drawer below 900px and the current pages avoid horizontal overflow at 390px.
- Mobile pages often stack large banners, headings, and metric cards before the first action, producing excessive scroll depth.
- Resume Corpus is responsive but its global+nested navigation model remains cognitively heavy.

### Performance

- The web app already uses server components and dynamic imports for several heavy client surfaces.
- Resume Corpus memoizes derived data and bounds the graph, but the route is a large static client bundle with no view-level code splitting, pagination, or virtualization.
- The global sidebar polls health every five seconds on every app page. This is acceptable locally but should pause when hidden/offline and avoid redundant server+client status checks.
- No production performance budget or layout-shift measurement exists.

## Safe change boundaries

Preserve these contracts during the UI redesign:

- `GET /tracker/summary`, `GET /applications`, and `PATCH /applications/{id}`
- `GET /jobs`
- `GET/POST /profile`
- `GET/POST/DELETE /accomplishments` through the existing compatibility adapter
- `POST /resume/generate` truth-safety behavior and source linking
- referral CRUD and ask-message endpoints
- extension download/info, email verification/send/thread, and outreach campaign endpoints
- legacy redirect routes and `/api/db` extension compatibility
- all user-owned Resume Corpus and recruiter-outreach work currently in the working tree

Do not introduce database migrations for visual redesign work. Do not claim multi-user security, durable goals, reminders, or scores until corresponding contracts exist.

## Product decisions

1. Build the Command Center from real stored state; use deterministic prioritization rules and explain them.
2. Replace implementation-based navigation groups with a seven-step career workflow while keeping route URLs stable.
3. Treat Resume Corpus as the deep “Strengthen” workspace and reduce global chrome around it rather than rebuilding its proven internals.
4. Turn Applications, Jobs, Connections, Interviews, and Insights into connected workspaces using existing data.
5. Introduce mature progress mechanics only where meaningful outcomes can be derived: evidence completion, follow-up completion, interview preparation, and pipeline movement. Do not create punitive daily streaks.
6. Use lightweight, accessible SVG/CSS visualizations for current data volume; do not add a chart dependency until interactions or dataset scale justify it.
7. Keep Roadmap, Guide, Settings, and ApplyPilot setup available as secondary resources instead of competing with daily work.

