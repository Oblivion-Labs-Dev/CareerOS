# CareerOS

AI-powered career operating system. Upload your resume, discover matched jobs, and let Autopilot fill and submit applications — all running locally.

## What it does

| Feature | Description |
|---|---|
| **Resume scan** | Upload a PDF → extracts name, contact, education, links, skills |
| **Browse Jobs** | Scrapes Greenhouse, Lever, Ashby, Workday, and 20+ sources |
| **Autopilot** | Chrome extension drives job forms end-to-end using your profile |
| **Application tracking** | Dashboard pipeline from saved → submitted → offer |
| **Resume intelligence** | Qwen-powered accomplishment extraction and job-fit scoring |

---

## Repository layout

```
CareerOS/
├── apps/
│   ├── api/          FastAPI backend (Python) — port 4000
│   └── web/          Legacy web location (active source is frontend/)
├── frontend/         Next.js dashboard — port 3000
├── extension/        Chrome MV3 extension (ApplyPilot)
├── packages/
│   ├── career-core/  Domain types, Zod schemas
│   └── career-ui/    Shared React components
├── infra/
│   ├── docker/       docker-compose.yml + docker-compose.repair.yml
│   ├── dev/          Dev lifecycle scripts (setup, restart, hooks)
│   └── ci/           CI scripts
├── scripts/          Root-level copies of infra/ scripts (for tooling compatibility)
├── tools/
│   ├── analysis/     Audit, benchmark, data-pull scripts
│   ├── inspection/   DB / payload inspection scripts
│   └── testing/      One-off test scripts
├── docs/             Architecture, planning, and reference docs
│   ├── AGENTS.md     AI agent instructions and safety rules
│   └── planning/     Task files, phase plans, overnight reports
└── data/             Runtime data — gitignored (DB, resumes, logs)
```

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Node.js | 20+ | (24 recommended — pnpm 11 requires Node 22.5+ built-in `sqlite`) |
| pnpm | 9+ | Activated via Corepack |
| Python | 3.11+ | For the FastAPI backend |
| [Ollama](https://ollama.com/) | any | Must be running; pull `qwen3:8b` |
| Docker (optional) | 20+ | Only needed for the Docker path |

---

## Quick start — local dev

```bash
# 1. Clone and enter
git clone <repo-url> CareerOS && cd CareerOS

# 2. Copy env template and fill in any API keys you have
cp .env.example .env

# 3. Install JS deps and build shared packages
pnpm install
pnpm --filter @career-os/core --filter @career-os/ui run build

# 4. Python virtualenv for the API
cd apps/api
python3 -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows
pip install -r requirements.txt
cd ../..

# 5. Pull the LLM (needed for Autopilot field mapping and resume scoring)
ollama pull qwen3:8b

# 6. Start everything
#   Terminal A — API on :4000
cd apps/api && .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 4000

#   Terminal B — Dashboard on :3000
pnpm --filter @career-os/web dev
```

Or use the all-in-one setup script (macOS/Linux):

```bash
./setup.sh          # installs deps, venv, Playwright, Ollama model
pnpm dev            # starts API + dashboard concurrently
```

### Verify

| Service | URL / command |
|---|---|
| API health | `curl http://localhost:4000/health` → `{"status":"ok"}` |
| Dashboard | http://localhost:3000 |
| Job discovery | http://localhost:3000/jobs/discover |
| Autopilot | http://localhost:3000/application-assistant |
| Diagnostics | http://localhost:3000/diagnostic |

---

## Quick start — Docker

```bash
# From repo root:
cp .env.example .env        # fill in keys if needed
docker compose up           # API on :4000, dashboard on :3000
```

Ollama must be running on the host with `qwen3:8b` pulled — the containers reach it at `host.docker.internal:11434`.

To work against a scratch database instead of your live one:

```bash
CAREEROS_DATA_DIR=/tmp/careeros-scratch docker compose up
```

---

## First-run checklist

After starting the servers, do these steps once in the UI:

1. **Profile → Upload resume** — drop in your PDF, the scan panel appears automatically. Review extracted fields, edit if needed, click "Save to profile".
2. **Profile → Application details** — fill in mailing address, work authorization, salary expectations (these are needed for job forms).
3. **Browse Jobs → Scrape** — click "Start scrape" to index jobs. Takes 2–5 minutes for the first run.
4. **Browse Jobs → Rescore** — after scraping, rescore matches against your profile.
5. **Autopilot → Load Chrome extension** — go to `chrome://extensions`, enable Developer mode, click "Load unpacked", point at `extension/dist/`.

---

## Key environment variables

All in `.env` at the repo root (copy from `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `CAREER_OS_DATABASE_URL` | `sqlite:///./data/career_os.db` | SQLite path (relative to `apps/api/`) |
| `APPLICATION_ASSISTANT_LLM_MODEL` | `qwen3:8b` | Ollama model for Autopilot |
| `APPLICATION_ASSISTANT_LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint |
| `CHRONOS_MAPPING_MODEL` | `qwen3:8b` | Model for field mapping agent |
| `ALLOW_REAL_SUBMISSION` | `false` | Set to `true` only when ready to submit live applications |
| `CAREER_OS_CORS_ORIGINS` | `http://localhost:3000,...` | Allowed CORS origins |
| `OPENROUTER_API_KEY` | _(blank)_ | Optional cloud LLM fallback |
| `GMAIL_USER` / `GMAIL_APP_PASSWORD` | _(blank)_ | For Gmail receipt parsing |

---

## Chrome extension

Build: `pnpm --filter @career-os/extension build`

Load in Chrome:
1. `chrome://extensions` → enable **Developer mode**
2. **Load unpacked** → select `extension/dist/`
3. Visit any job application page — the extension activates automatically

---

## Troubleshooting

**"0 jobs found" in Browse Jobs** — scrape hasn't run yet. Click "Start scrape" on the Browse Jobs page, or POST to `http://localhost:4000/jobs/discover/scrape`.

**Autopilot says LLM unavailable** — confirm Ollama is running (`ollama list`) and the model matches `APPLICATION_ASSISTANT_LLM_MODEL` in `.env`. Default is `qwen3:8b`.

**"Failed to load resume profiles" or proxy errors** — ensure the frontend is running from `frontend/` (not `apps/web/`). The correct dev command is `pnpm --filter @career-os/web dev` from the repo root.

**API unreachable from browser** — check `NEXT_PUBLIC_API_URL` in `frontend/.env.local`. Should be `http://localhost:4000`.

**Hydration mismatch warning** — browser extensions (1Password, etc.) inject attributes after SSR. Harmless — suppressed on `<body>` already.

---

## Docs

- [`docs/AGENTS.md`](./docs/AGENTS.md) — AI agent rules, safety constraints, submission guard
- [`docs/planning/`](./docs/planning/) — Architecture, task files, phase plans
- [`docs/docker.md`](./docs/docker.md) — Docker-specific notes (data dirs, GPU flags, hot reload)
