from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.error_fix_tracker import TrackedEvent, error_fix_tracker
from app.services.log_store import read_client_logs
from app.services.runtime_metrics import metrics_store

REPO_ROOT = Path(__file__).resolve().parents[3]


def _source_hints(source: str, signature: str) -> list[str]:
    hints: list[str] = []
    if source == "api" or signature.startswith(("GET ", "POST ", "PUT ", "PATCH ", "DELETE ")):
        hints.append("apps/api/app/routers/api.py")
        hints.append("apps/api/app/main.py")
        route = signature.split(" ", 1)[-1] if " " in signature else signature
        if route.startswith("/"):
            hints.append(f"Search API handlers for route `{route}`")
    if source == "client" or signature.startswith("extension:"):
        hints.append("apps/extension/src/content/")
        hints.append("apps/extension/src/background/")
        hints.append("apps/extension/src/shared/")
    if "typescript" in signature.lower() or "web:" in signature.lower():
        hints.append("apps/web/")
    if not hints:
        hints.append("CareerOS monorepo root")
    return hints


def _recent_log_lines(limit: int = 6) -> list[str]:
    lines: list[str] = []
    for entry in read_client_logs(limit=limit):
        level = str(entry.get("level") or "info")
        source = str(entry.get("source") or "client")
        message = str(entry.get("message") or "")
        ts = str(entry.get("ts") or "")
        lines.append(f"[{level}] {source}: {message} ({ts})")
    return lines


def _recent_request_lines(limit: int = 8) -> list[str]:
    snapshot = metrics_store.snapshot()
    lines: list[str] = []
    for item in snapshot.get("recentRequests") or []:
        lines.append(
            f"{item.get('method')} {item.get('path')} -> {item.get('status')} ({item.get('durationMs')} ms)"
        )
        if len(lines) >= limit:
            break
    return lines


def build_investigation_payload(error: TrackedEvent) -> dict[str, Any]:
    hints = _source_hints(error.source, error.signature)
    log_lines = _recent_log_lines()
    request_lines = _recent_request_lines()
    status_line = f"HTTP {error.status_code}" if error.status_code else "n/a"
    at_iso = datetime.fromtimestamp(error.at, tz=UTC).isoformat()

    prompt = f"""Investigate and fix this CareerOS live error.

## Error
- ID: {error.id}
- Source: {error.source}
- Signature: {error.signature}
- Status: {status_line}
- Detected: {at_iso}
- Message: {error.message}

## Likely code areas
{chr(10).join(f"- {hint}" for hint in hints)}

## Recent extension/client logs
{chr(10).join(f"- {line}" for line in log_lines) if log_lines else "- none"}

## Recent API requests
{chr(10).join(f"- {line}" for line in request_lines) if request_lines else "- none"}

## Task
1. Find the root cause in the repo at `{REPO_ROOT}`.
2. Apply the smallest correct fix.
3. Run relevant tests (API: `python -m pytest` in apps/api; extension: `pnpm test` in apps/extension; web: `pnpm exec tsc --noEmit` in apps/web).
4. Summarize what broke and what you changed.

Do not auto-deploy or push unless explicitly asked."""

    return {
        "errorId": error.id,
        "signature": error.signature,
        "source": error.source,
        "message": error.message,
        "statusCode": error.status_code,
        "detectedAt": at_iso,
        "prompt": prompt,
        "hints": hints,
        "repoRoot": str(REPO_ROOT),
    }


def investigation_for_error_id(error_id: str, *, mark_requested: bool = False) -> dict[str, Any]:
    error = error_fix_tracker.find_error(error_id)
    if not error:
        raise ValueError(f"Error `{error_id}` not found")
    if mark_requested:
        error_fix_tracker.mark_investigation_requested(error_id)
    payload = build_investigation_payload(error)
    payload["investigationRequested"] = mark_requested
    return payload


def investigation_for_open_errors() -> dict[str, Any]:
    open_errors = error_fix_tracker.list_open_errors()
    if not open_errors:
        raise ValueError("No open errors to investigate")

    sections: list[str] = []
    for index, error in enumerate(open_errors, start=1):
        build_investigation_payload(error)
        sections.append(
            f"### Error {index}: {error.signature}\n"
            f"- ID: {error.id}\n"
            f"- Source: {error.source}\n"
            f"- Message: {error.message}\n"
        )

    prompt = f"""Investigate and fix these {len(open_errors)} open CareerOS errors (priority order).

{chr(10).join(sections)}

## Instructions
Work through each error one at a time. For each:
1. Diagnose root cause in `{REPO_ROOT}`
2. Apply minimal fix
3. Run targeted tests
4. Note which error IDs are resolved

Do not auto-deploy or push unless explicitly asked."""

    return {
        "errorIds": [error.id for error in open_errors],
        "openCount": len(open_errors),
        "prompt": prompt,
        "errors": [build_investigation_payload(error) for error in open_errors],
        "repoRoot": str(REPO_ROOT),
    }
