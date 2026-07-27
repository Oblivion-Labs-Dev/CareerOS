# Repair orchestrator

Local automated error detection and software-repair pipeline for CareerOS.

## Quick start

From the CareerOS repo root:

```bash
# Install orchestrator dependencies (once)
pip install -r tools/repair-orchestrator/requirements.txt

# Start the repair stack
pnpm repair:up

# In another terminal, enable API forwarding + demo route
# apps/api/.env
# CAREER_OS_REPAIR_ENABLED=true
# CAREER_OS_REPAIR_DEMO_ENABLED=true
# CAREER_OS_REPAIR_ORCHESTRATOR_URL=http://127.0.0.1:8090

pnpm dev:api
pnpm dev:web
```

Open the developer dashboard: http://localhost:3000/dev/repair

## Trigger the demonstration incident

1. Ensure the orchestrator is running (`pnpm repair:up`).
2. Enable repair flags in `apps/api/.env`.
3. Open http://localhost:3000/dev/repair and click **Trigger demo incident**, or:

```bash
curl -i http://127.0.0.1:8000/dev/demo/unhandled-scraper-error
```

4. Trigger the endpoint twice so occurrence thresholds create a repair task automatically.
5. Use dashboard actions: approve agent → validate → review.

## Architecture

- **Structured error capture** — CareerOS API emits sanitized JSON via `apps/api/app/services/structured_errors.py`.
- **Repair orchestrator** — FastAPI service in `tools/repair-orchestrator/` with SQLite persistence.
- **Incident grouping** — Stable SHA-256 fingerprint from error type, service, stack location, endpoint.
- **Repair tasks** — Lifecycle states from `detected` through `closed` / `failed`.
- **Coding-agent adapter** — `CodingAgentAdapter` interface with a local mock adapter that creates isolated git worktrees.
- **Deterministic validation** — Shell commands from config; failures block approval.
- **Independent review** — Separate mock reviewer returns structured JSON decisions.
- **PR handoff** — Draft title/body stored on the task; no automatic push/merge.

See `docs/automated-repair-system.md` for full documentation.

## Tests

```bash
cd tools/repair-orchestrator && python -m pytest tests -q
cd apps/api && python -m pytest tests/test_repair_pipeline.py -q
```

## Cleanup worktrees

```bash
git worktree list
git worktree remove .repair-worktrees/<id>
git branch -D repair/<task-id>-<slug>
```
