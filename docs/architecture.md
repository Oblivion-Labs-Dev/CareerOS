# CareerOS Architecture

## Layered architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Presentation                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Next.js Web  │  │ Chrome Ext.  │  │ Extension Portal │  │
│  │  Dashboard   │  │  ApplyPilot  │  │   / Dashboard  │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
└─────────┼─────────────────┼───────────────────┼────────────┘
          │                 │                   │
          └─────────────────┼───────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  API — FastAPI (apps/api)                                   │
│  REST endpoints + legacy /api/db sync for extension         │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Domain — career-core (schemas, roadmap, business types)    │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Infrastructure — Arsenal (logging, LLM, shared utilities)  │
└─────────────────────────────────────────────────────────────┘
```

## Chrome extension flow

1. **Content script** scans job/application pages for form fields and job metadata.
2. **Field classifier** maps DOM labels to canonical profile keys; unknown fields prompt the user.
3. **Autofill runner** fills text/select/file inputs and attaches resume/cover letter.
4. **Learning engine** persists question/answer pairs and field mappings to IndexedDB.
5. **Sync layer** pushes/pulls data to the CareerOS API (`/api/db` legacy + REST endpoints).
6. **Popup** exposes scan, autofill, save job, cover letter, and tracker actions.

## Backend flow

- FastAPI serves all CareerOS endpoints on port **8000** by default.
- SQLite in dev (`CAREER_OS_DATABASE_URL`); schema is PostgreSQL-ready via SQLAlchemy.
- Legacy `/api/db` GET/POST maintains compatibility with the migrated extension sync.
- Resume parsing via `pypdf` hydrates profile fields from uploaded PDFs.
- Cover letter and question endpoints are scaffolded; LLM integration will use Arsenal OpenRouter client.

## Dashboard flow

- Next.js App Router with shared `@career-os/ui` components.
- Server components fetch API data where available (jobs, applications, mappings).
- `/roadmap` renders module-grouped feature cards from `@career-os/core`.

## Arsenal dependency boundaries

**Import from Arsenal:** generic utilities only (`@oblivion-labs-dev/arsenal-shared`, logging, telemetry).

**Do not import from Arsenal:** job types, autofill logic, application models, recruiter scripts.

## Data model overview

| Entity | Description |
|--------|-------------|
| UserProfile | Contact, work auth, screening defaults, work experience |
| Resume | Stored document + parsed text |
| Job | Extracted/saved posting metadata |
| Application | Pipeline record linked to job/company |
| Company | Employer metadata |
| Recruiter | CRM contact |
| AutofillFieldMapping | Learned label → canonical key |
| ApplicationQuestion | Screening Q&A |
| CoverLetter | Generated or uploaded letter |
| Interview | Scheduled prep session |
| Referral | Networking referral |
| CareerEvent | Analytics/activity event |
| Skill / Project / Education / Experience | Profile enrichment |

Schemas live in `packages/career-core/src/schemas`.
