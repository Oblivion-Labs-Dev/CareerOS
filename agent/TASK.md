# Task: Containerize CareerOS Development Stack

## Goal

Add a reproducible Docker Compose development environment for CareerOS.

Target:

```text
Docker Compose
├── web          → Next.js :5000
├── api          → FastAPI :4000
└── playwright   → Chromium/browser automation

Host
├── Existing MySQL
└── Ollama
```

The desired developer experience is:

```bash
docker compose up
```

Docker must be an additional supported development environment. Do not break the existing Windows/local workflow.

---

## Before Coding

Follow `AGENTS.md`.

Read:

* `agent/ARCHITECTURE.md`
* this task in `agent/TASK.md`

Then inspect the actual implementation before making changes.

Specifically understand:

* Web/API startup and dependencies
* environment/config loading
* MySQL connection
* Ollama connection
* Autopilot runner
* `playwright_autopilot_executor.py`
* how API and Playwright currently communicate
* Chromium installation/configuration
* browser authentication/session handling
* screenshots, downloads, and application evidence
* filesystem paths that require persistence

Trace:

```text
Web
→ API
→ Autopilot Runner
→ Playwright
→ Job Site
→ Evidence
→ Application State
```

State a short implementation plan before editing.

Code is the source of truth. Adapt the Docker design to the existing architecture rather than forcing unnecessary architectural changes.

---

## Requirements

### Web

Containerize the existing Next.js application.

* Expose port `5000`.
* Preserve development behavior/hot reload where practical.
* Communicate with the API through configurable environment settings.

### API

Containerize the existing FastAPI application.

* Expose port `4000`.
* Reuse existing Python dependency configuration.
* Do not create a second dependency system unnecessarily.

### Playwright

Containerize Playwright and Chromium.

Prefer a separate browser/worker service if it fits the existing architecture cleanly.

Do not introduce a new queue, RPC system, or major worker architecture solely to achieve containerization.

Use a Playwright-compatible container/base image and keep browser and Playwright versions compatible.

Determine from the existing implementation whether CareerOS requires:

* headless Chromium
* headed Chromium
* persistent browser profiles
* Playwright storage state

Do not assume.

### Browser Persistence

Container restarts must not silently destroy browser state required by CareerOS.

Persist where appropriate:

* authentication/session state
* browser profiles
* screenshots
* downloads
* application evidence

Never bake authenticated sessions into an image.

Sensitive browser state must remain local and gitignored.

### MySQL

**Do not containerize or migrate MySQL in this task.**

CareerOS must continue using the existing host MySQL database and all existing data.

Use configurable networking such as:

```text
host.docker.internal
```

where appropriate.

Do not:

* reset the database
* recreate the database
* migrate data to another MySQL instance
* modify existing data for Docker testing
* mount the existing MySQL data directory into Docker

Existing local configuration using `localhost` must continue working.

### Ollama

Keep Ollama running on the host.

Allow the appropriate CareerOS containers to access it through configurable networking.

Do not containerize models or duplicate Ollama model storage.

---

## Networking

The resulting environment should support:

```text
Browser/User
     ↓
Web :5000
     ↓
API :4000
     ↓
┌───────────────┬───────────────┬──────────────┐
Playwright      Host MySQL      Host Ollama
```

Do not hardcode Docker-specific hostnames into CareerOS business logic.

Use environment/configuration overrides.

---

## Safety

Preserve all existing CareerOS safeguards.

Especially:

* duplicate-application protection
* human review for unresolved answers
* selected resume mode
* submission verification
* approved-job restrictions
* application lifecycle/state handling

Containerization must not change application behavior.

Do not run real applications during this task.

Do not commit:

* credentials
* `.env` secrets
* browser sessions
* private resumes
* application logs/evidence
* MySQL data

---

## Docker Structure

Prefer a small conventional setup such as:

```text
CareerOS/
├── docker-compose.yml
├── .dockerignore
│
├── apps/
│   ├── web/
│   │   └── Dockerfile
│   │
│   └── api/
│       └── Dockerfile
│
└── ...
```

If Playwright requires its own Dockerfile/service location, place it where it naturally fits the existing architecture.

Do not reorganize the repository merely for Docker.

Use volumes only where persistence or development mounting is actually required.

Add useful health checks where practical.

---

## Verification

Verify incrementally.

### Existing Environment

Confirm the existing non-Docker development workflow remains functional.

### Docker

Confirm:

1. `docker compose up` starts CareerOS.
2. Web starts on `5000`.
3. API starts on `4000`.
4. Web communicates with API.
5. API connects to the existing host MySQL.
6. Existing MySQL data remains accessible and unchanged.
7. CareerOS can reach host Ollama.
8. Playwright launches Chromium successfully.
9. CareerOS can trigger the containerized Playwright flow.
10. Safe browser navigation works without submitting an application.
11. Required browser state survives container restart.
12. Screenshots/evidence persist where expected.
13. Relevant backend tests pass.
14. Frontend typecheck passes.

Do not use a real application submission as verification.

---

## Regression Protection

If containerization exposes an existing bug, distinguish between:

```text
Docker configuration problem
vs.
existing CareerOS application bug
```

Do not silently modify unrelated CareerOS behavior.

For reproducible application bugs, follow the regression process defined in `AGENTS.md`.

---

## Documentation

Document the final developer workflow, including:

```bash
docker compose up
docker compose down
docker compose logs
```

Also document:

* environment variables
* Web/API ports
* host MySQL connectivity
* host Ollama connectivity
* Playwright architecture
* browser-state persistence
* artifact persistence
* how to inspect Playwright logs
* Docker vs local development differences
* known limitations

Update `agent/ARCHITECTURE.md` only if the resulting runtime architecture materially changes.

---

## Definition of Done

The task is complete when:

```text
docker compose up
```

provides a working CareerOS development environment containing Web, API, and Playwright while:

* existing host MySQL and its data remain untouched
* Ollama remains on the host
* browser state/evidence are safely handled
* no CareerOS safeguards are weakened
* no real applications were submitted during testing
* the original local development workflow still works

At completion report:

1. Final container architecture
2. Files changed
3. How persistence works
4. How MySQL and Ollama are reached
5. Tests/checks performed
6. Any remaining limitations
