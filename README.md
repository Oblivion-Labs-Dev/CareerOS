# CareerOS

CareerOS is an AI-powered career operating system. The first working module is **ApplyPilot** (formerly JobFill): a Chrome extension plus backend workflow for job application autofill, resume attachment, cover letter generation, application tracking, and self-learning field mapping.

## Architecture

```
CareerOS/
  apps/
    web/          Next.js dashboard
    extension/    ApplyPilot Chrome MV3 extension
    api/          FastAPI backend
  packages/
    career-core/  Domain types, Zod schemas, roadmap data
    career-ui/    Career-specific React UI components
  docs/
```

CareerOS is self-contained: it builds and runs without any other repository. Some of its code was migrated from the older Arsenal repo (see [docs/migration-from-arsenal.md](./docs/migration-from-arsenal.md)), but nothing depends on Arsenal any more.

## Current priority: ApplyPilot MVP

Phase 1 focuses on profile sync, resume storage, job extraction, autofill detection/execution, unknown-field learning, save application, and the basic dashboard.

## Prerequisites

- Node.js 20+
- pnpm 9+ (setup enables via Corepack)
- Python 3.11+
- [Ollama](https://ollama.com/) with **qwen3:8b** (setup installs and pulls this)

## First-time setup

**Windows**

```bat
git clone <careeros-repo-url> CareerOS
cd CareerOS
setup.bat
```

**macOS / Linux**

```bash
git clone <careeros-repo-url> CareerOS
cd CareerOS
chmod +x setup.sh scripts/setup.sh
./setup.sh
```

The setup script will:

1. Check Node 20+, Python 3.11+, and pnpm
2. Create `.env`, `apps/api/.env`, and `apps/web/.env.local`
3. Run `pnpm install`
4. Create `apps/api/.venv`, install Python deps, and install Playwright Chromium
5. Install Ollama (if missing), start it, and pull **qwen3:8b**
6. Build the Chrome extension
7. Run API smoke tests

Options (PowerShell): `.\scripts\setup.ps1 -SkipOllama`, `-SkipModels`, `-SkipExtension`, `-SkipTests`, `-Model qwen2.5:7b`

Then start dev servers:

```bat
restart-dev.bat -Background
```

Or: `pnpm dev`

## Local development (manual)

```bash
# From CareerOS/
cp .env.example .env

# Install JS dependencies
pnpm install

# Terminal 1 — API (port 8000)
cd apps/api
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
pnpm dev

# Terminal 2 — Web dashboard (port 3000)
pnpm dev:web

# Terminal 3 — Extension
pnpm --filter @career-os/extension build
# Load apps/extension/dist in chrome://extensions (Developer mode)
```

### Verify

| Check | Command / URL |
|-------|----------------|
| API health | `curl http://localhost:8000/health` |
| Dashboard | http://localhost:3000/dashboard |
| Roadmap | http://localhost:3000/roadmap |
| Extension | Build output in `apps/extension/dist` |

## Apps & packages

| Package | Purpose |
|---------|---------|
| `@career-os/web` | CareerOS dashboard and roadmap command center |
| `@career-os/extension` | ApplyPilot Chrome extension (MV3) |
| `@career-os/api` | FastAPI REST backend |
| `@career-os/core` | Shared schemas, types, roadmap definitions |
| `@career-os/ui` | Reusable career UI components |

## History: Arsenal

CareerOS started out alongside the Arsenal repository and has since absorbed everything it used from it; it no longer depends on Arsenal in code, build, CI or setup. See [docs/migration-from-arsenal.md](./docs/migration-from-arsenal.md) for the migration log.

## Documentation

- [Architecture](./docs/architecture.md)
- [Roadmap](./docs/roadmap.md)
- [Migration from Arsenal](./docs/migration-from-arsenal.md)

## License

Private — Oblivion Labs.
