# Migration from Arsenal

This document records what moved from the Arsenal monorepo into CareerOS and what remains in Arsenal.

## What was moved

### `Arsenal/packages/jobfill-extension` → `CareerOS/apps/extension`

The entire ApplyPilot/JobFill Chrome MV3 extension:

| Area | Path (in CareerOS) |
|------|---------------------|
| Content scripts & autofill | `apps/extension/src/content/` |
| Background service worker | `apps/extension/src/background/` |
| Popup UI | `apps/extension/src/popup/` |
| Extension dashboard & portal | `apps/extension/src/dashboard/`, `portal/` |
| Profile & documents | `apps/extension/src/profile/`, `documents/` |
| Learning engine | `apps/extension/src/learning/` |
| IndexedDB layer | `apps/extension/src/db/` |
| Application tracker | `apps/extension/src/tracker/` |
| E2E fixtures & tests | `apps/extension/e2e/`, `fixtures/` |

### Backend dev server → `CareerOS/apps/api`

| Former location | New location |
|-----------------|--------------|
| `jobfill-extension/server.js` | Replaced by FastAPI (`apps/api/app/`) |
| `jobfill-extension/server.py` | Removed (FastAPI is canonical) |
| `jobfill-extension/server/resumeParser.js` | Ported to `apps/api/app/services/resume_parser.py` |
| `jobfill-extension/server/logStore.js` | Ported to `apps/api/app/services/log_store.py` |

### Domain types (new, extracted from extension)

Career-specific types now live in `@career-os/core` (`packages/career-core/src/schemas/`) instead of extension-local `shared/types.ts`. Extension types remain locally for now; gradual consolidation is planned.

## What stayed in Arsenal

These packages remain domain-agnostic:

- `@oblivion-labs-dev/arsenal-shared` — Result types, formatting, OpenRouter constants
- `@oblivion-labs-dev/arsenal-logging`
- `@oblivion-labs-dev/arsenal-telemetry`
- `@oblivion-labs-dev/arsenal-models`, `memory`, `scheduler`, `tools`, `testing`

### Not yet migrated (TODO)

| Asset | Location | Target |
|-------|----------|--------|
| Recruiter email scripts | `Arsenal/scripts/email/` | `CareerOS/apps/api` or automation module |
| Recruiter JSON data | `Arsenal/scripts/email/recruiters*.json` | CareerOS recruiter CRM |

## Import changes

### Extension

```ts
// Before (Arsenal)
"@oblivion-labs-dev/arsenal-jobfill-extension"

// After (CareerOS)
"@career-os/extension"
"@career-os/core"           // shared schemas (workspace)
"@oblivion-labs-dev/arsenal-shared"  // generic utilities only
```

### API URL

```ts
// Before
http://localhost:8085/api/db

// After
http://localhost:8000/api/db   // legacy sync
http://localhost:8000/profile  // REST endpoints
```

Centralized in `apps/extension/src/shared/apiConfig.ts`.

### Workspace linking

`CareerOS/pnpm-workspace.yaml` includes:

```yaml
- "../Arsenal/packages/shared"
- "../Arsenal/packages/logging"
- "../Arsenal/packages/telemetry"
```

## Arsenal cleanup

- `Arsenal/packages/jobfill-extension/` **removed**
- No career-specific code should remain in Arsenal packages

## Unresolved / follow-up

1. **Full resume parser parity** — Python parser implements core email/phone/name extraction; JS parser had richer work-experience parsing. Port remaining logic or call shared WASM/service.
2. **Extension type consolidation** — Migrate `apps/extension/src/shared/types.ts` to import from `@career-os/core`.
3. **E2E port references** — Playwright configs still reference port 8085; update to 8000 when running e2e against FastAPI.
4. **Recruiter email scripts** — Still in Arsenal; move when Recruiter CRM module starts.
5. **LLM cover letters** — Template-based generation in API; wire OpenRouter via Arsenal when `OPENROUTER_API_KEY` is set.
6. **PostgreSQL** — SQLAlchemy models ready; switch `CAREER_OS_DATABASE_URL` for production.
