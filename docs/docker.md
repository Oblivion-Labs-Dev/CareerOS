# Running CareerOS in Docker

Docker is an **additional** development environment. The Windows/local workflow
(`scripts/restart-dev.ps1`, `pnpm dev`) is unchanged and remains the primary way
to run CareerOS — in particular it is the only way to run the headed,
assisted-fill browser flow.

```bash
docker compose up          # build (first run) and start web + api
docker compose up -d       # same, detached
docker compose down        # stop and remove containers (volumes survive)
docker compose logs -f api # follow API + Playwright logs
docker compose logs -f web # follow Next.js logs
```

| Service | Port | Contains |
|---|---|---|
| `web` | http://localhost:5000 | Next.js dev server, hot reload |
| `api` | http://localhost:4000 | FastAPI **+ Playwright + Chromium** |

Host-side, unchanged: **Ollama** on `:11434`, and the **SQLite database**.

---

## Do not run Docker and the local servers at the same time

Both write the same SQLite file and the same browser profile, and `app/main.py`
refuses to start with more than one worker because Autopilot state (browser
sessions, task handles, the scrape task, the read cache) is process-local. Two
API processes against one database is the single configuration that can corrupt
application state.

Stop the local stack first, or point Docker at a scratch copy:

```bash
# in the repository-root .env
CAREEROS_DATA_DIR=./apps/api/.docker-data
```

---

## There is no MySQL

Despite what you may expect from the service list, CareerOS does not use MySQL
and never has. `apps/api/.env` sets:

```
CAREER_OS_DATABASE_URL=sqlite:///./data/career_os.db
```

No MySQL driver is installed, and `app/db/store.py` is SQLite-specific
throughout — WAL pragmas, `json_extract`/`json_set`, and an
`INSERT … ON CONFLICT` upsert used for the application-identity claim.

So there is **no database container**, nothing is migrated, and no data is
copied. The API container opens the *existing* database file through a bind
mount of `apps/api/data`. Your existing applications, answers and evidence are
the ones the container sees.

> **Known limitation.** SQLite in WAL mode over a Docker Desktop bind mount from
> a Windows host crosses a virtual filesystem boundary, where file locking is
> less reliable than on a native disk. Expect occasional `database is locked`
> under write contention, and do not run a long unattended batch this way. For
> heavy Autopilot work, use the local workflow. This is a property of SQLite
> over virtualised mounts, not a CareerOS bug.

---

## How the pieces reach each other

```
Browser → web :5000
            │  server-side proxy: apps/web/app/api/backend/[...path]/route.ts
            ▼
          api :4000  ──► Playwright + Chromium (same container)
            │
            ├──► host Ollama   http://host.docker.internal:11434
            └──► SQLite        bind-mounted ./apps/api/data
```

`host.docker.internal` resolves to the host from inside a container. The
`extra_hosts: host.docker.internal:host-gateway` entry makes that work on Linux
too, where it is not automatic.

Nothing Docker-specific is compiled into CareerOS. The application keeps its
`localhost` defaults and every hostname is an environment override.

---

## Why Playwright is not its own service

The task sketch showed a separate `playwright` container. It does not fit this
codebase, and forcing it would have cost more than it bought.

The API drives the browser **in-process**: `browser_runner.py` owns a dedicated
event-loop thread and hands live Playwright objects straight to
`playwright_autopilot_executor.py`. There is no wire protocol between them.

More decisively, the assisted-fill path calls:

```python
chromium.launch_persistent_context(profile_dir, channel="chrome", ...)
```

A **persistent context cannot be driven over Playwright's `connect()`** — that
API only hands back ordinary browser instances. Splitting the browser into its
own container would therefore require either inventing an RPC layer (which the
task forbids) or dropping assisted fill under Docker, which would make container
behaviour differ from local behaviour.

So Chromium ships inside the API image, built from
`mcr.microsoft.com/playwright/python:v1.61.0-noble`. The tag is pinned to the
exact `playwright` version in `requirements.txt` so the driver and browser build
cannot drift apart. **When you bump `playwright`, bump the base image tag.**

---

## Browser state, evidence and persistence

| Path | Mount | Holds |
|---|---|---|
| `/app/apps/api/data` | bind → `./apps/api/data` | SQLite DB, browser profiles, screenshots, tailored resumes, traces |
| `/models` | named volume `careeros-models` | Hugging Face embedding weights |
| `/app/data` | baked into both images | Two git-tracked seed files (see below) |

### The repository-root `data/` directory is not the same thing

`apps/api/data/` is live runtime state and is excluded from every image. The
repository-root `data/` is different: two of its files are tracked in git and are
source, and both are resolved from *outside* the app that needs them.

* `data/resume-corpus-initial.json` — imported directly by
  `apps/web/app/(app)/resume-corpus/corpus-seed-data.ts`, and read by
  `store.py` as `parents[4]/data/...` for seeding.
* `data/interview-story-corpus.json` — loaded by `services/story_index.py`,
  which is the corpus resume tailoring retrieves evidence from.

A blanket `data/` rule in `.dockerignore` caught both. The web typecheck failed
loudly on the missing import; the API failed **silently** — `/app/data` simply
did not exist, so the story index had no corpus and evidence retrieval would
have quietly degraded. `.dockerignore` now re-includes exactly these two files.

Browser profiles live under `data/application_assistant/browser_profile`, and
`AA_BROWSER_PROFILE_DIR` points the container at that mounted path, so a
logged-in session survives `docker compose down`.

Authenticated sessions are **never baked into an image**. `.dockerignore`
excludes `.env`, `apps/api/data/`, every `browser_profile/`, `chrome-profile/`
and `sessions/` directory, `apps/web/e2e/.auth/`, and private resumes. Sensitive
browser state reaches a container through a volume at run time or not at all.

The embeddings volume matters for quality, not crashes: `semantic.py` loads with
`local_files_only=True` and degrades to BM25 when weights are absent, so an
unpersisted cache quietly makes resume ranking worse rather than failing.
Populate it with `apps/api/scripts/warm_embeddings.py`.

---

## Environment variables

All optional — every one has a working default. Copy `.env.docker.example` to
the repository-root `.env` to change them.

| Variable | Default | Purpose |
|---|---|---|
| `CAREEROS_DATA_DIR` | `./apps/api/data` | Host directory bind-mounted as the data dir |
| `CAREER_OS_DATABASE_URL` | `sqlite:///./data/career_os.db` | SQLite path, relative to the API workdir |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434/v1` | Inference endpoint |
| `APPLICATION_ASSISTANT_LLM_BASE_URL` | same | Inference endpoint |
| `CAREEROS_OLLAMA_HEALTH_URL` | `http://host.docker.internal:11434` | Liveness probes (no `/v1`) |
| `CAREEROS_DOCKER_API_URL` | `http://api:4000` | Web → API inside the compose network |
| `AA_HEADLESS` | `true` | Headless Chromium |
| `ALLOW_REAL_SUBMISSION_DOCKER` | `false` | See below |

### `ALLOW_REAL_SUBMISSION` is forced off in Docker

`apps/api/.env` sets `ALLOW_REAL_SUBMISSION=true` for the local workflow, and
Compose's `env_file` would have carried that straight into the container. The
compose `environment:` block overrides it to `false`, because `environment` wins
over `env_file`.

That guard is what `submission_guard.assert_submission_permitted()` checks
before a final submit click. Turning it on means real applications go to real
employers, so it is opt-in and deliberate:

```bash
ALLOW_REAL_SUBMISSION_DOCKER=true docker compose up
```

Everything else in AGENTS.md still applies — live runs also need
`CAREEROS_LIVE_APPLY=1` and an explicit `CAREEROS_APPROVED_JOB_IDS` allowlist.

---

## Docker vs local: what differs

| | Local | Docker |
|---|---|---|
| Headless Autopilot | yes | yes |
| **Headed / assisted fill** | **yes** | **no — no display, and `channel="chrome"` needs real Chrome** |
| Hot reload | yes | yes (polling; slightly slower) |
| SQLite performance | native | slower, locking less reliable over the mount |
| Ollama | same process host | reached over `host.docker.internal` |
| First start | seconds | minutes (multi-GB image build) |

The headed limitation is the important one. <br>
`leave-assisted-fill-browser-open` behaviour — where the window stays open for
you to finish an application by hand — is a local-only workflow.

---

## Inspecting Playwright

Playwright logs to the API container's stdout and to the shared log file:

The API image installs `requirements-dev.txt`, so the suite runs where the code
runs:

```bash
docker compose exec api python -m pytest tests -q
docker compose exec web node /app/node_modules/typescript/bin/tsc --noEmit
```

```bash
docker compose logs -f api
docker compose exec api tail -f data/logs/api.log
docker compose exec api python -c "from playwright.sync_api import sync_playwright;
p=sync_playwright().start(); b=p.chromium.launch(); print('chromium', b.version); b.close(); p.stop()"
```

Screenshots and traces land in the mounted data directory and are readable from
the host at `apps/api/data/application_assistant/`.

`shm_size: 1gb` is set because Chromium crashes on content-heavy pages with
Docker's default 64 MB of shared memory.

---

## Known limitations

1. **Headed/assisted fill does not work in Docker.** Use the local workflow.
2. **SQLite over a Windows bind mount** can hit `database is locked`; avoid long
   unattended batches in Docker.
3. **Large images.** The API image carries Chromium plus PyTorch (via
   `sentence-transformers`) — several GB, and the first build is slow.
4. **Never run Docker and the local servers together** against the same data
   directory.
5. `apps/extension` is not containerized; it is a browser add-on built locally.
6. This targets development. A production image would add a `next build` stage
   and drop the source bind mounts.
