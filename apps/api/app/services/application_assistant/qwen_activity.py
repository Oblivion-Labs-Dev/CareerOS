"""Qwen / local LLM activity logging and metrics."""

from __future__ import annotations

import time
from datetime import UTC
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import get_kv, new_id, now_iso, set_kv
from app.services.application_assistant.log_redaction import redact_string

KV_LOGS = "qwen_activity_logs"
KV_METRICS = "qwen_activity_metrics"
MAX_LOGS = 200


def _default_metrics() -> dict[str, Any]:
    return {
        "totalRequests": 0,
        "successCount": 0,
        "errorCount": 0,
        "chatCount": 0,
        "completionCount": 0,
        "totalLatencyMs": 0,
        "lastRequestAt": None,
        "lastError": None,
        "model": "",
        "provider": "ollama",
        "connected": False,
        "lastCheckedAt": None,
    }


def get_metrics(db: Session) -> dict[str, Any]:
    stored = get_kv(db, KV_METRICS) or _default_metrics()
    avg_latency = 0.0
    if stored.get("successCount", 0) > 0:
        avg_latency = round(stored.get("totalLatencyMs", 0) / stored["successCount"], 1)
    return {
        **stored,
        "avgLatencyMs": avg_latency,
        "errorRate": round(
            (stored.get("errorCount", 0) / max(stored.get("totalRequests", 1), 1)) * 100,
            1,
        ),
    }


def update_connection_status(db: Session, *, connected: bool, model: str = "") -> dict[str, Any]:
    metrics = get_metrics(db)
    metrics["connected"] = connected
    metrics["lastCheckedAt"] = now_iso()
    if model:
        metrics["model"] = model
    set_kv(db, KV_METRICS, metrics)
    return metrics


def get_logs(db: Session, *, limit: int = 50) -> list[dict[str, Any]]:
    logs = get_kv(db, KV_LOGS) or []
    return logs[:limit]


def append_log(
    db: Session,
    *,
    event_type: str,
    model: str,
    success: bool,
    latency_ms: int,
    summary: str = "",
    error: str = "",
    metadata: dict[str, Any] | None = None,
    count_as_request: bool = True,
) -> dict[str, Any]:
    metrics = get_kv(db, KV_METRICS) or _default_metrics()
    if count_as_request:
        metrics["totalRequests"] = metrics.get("totalRequests", 0) + 1
        metrics["totalLatencyMs"] = metrics.get("totalLatencyMs", 0) + latency_ms
        metrics["lastRequestAt"] = now_iso()
        if success:
            metrics["successCount"] = metrics.get("successCount", 0) + 1
        else:
            metrics["errorCount"] = metrics.get("errorCount", 0) + 1
            metrics["lastError"] = redact_string(error)[:200]
        if event_type == "chat":
            metrics["chatCount"] = metrics.get("chatCount", 0) + 1
        elif event_type.startswith("agent_") or event_type == "completion":
            metrics["completionCount"] = metrics.get("completionCount", 0) + 1
    if model:
        metrics["model"] = model
    set_kv(db, KV_METRICS, metrics)

    entry = {
        "id": new_id("qlog_"),
        "timestamp": now_iso(),
        "type": event_type,
        "model": model,
        "success": success,
        "latencyMs": latency_ms,
        "summary": redact_string(summary)[:300],
        "error": redact_string(error)[:200] if error else "",
        "metadata": metadata or {},
    }

    logs = get_kv(db, KV_LOGS) or []
    logs.insert(0, entry)
    set_kv(db, KV_LOGS, logs[:MAX_LOGS])
    db.flush()
    return entry


def log_activity_event(
    *,
    event_type: str,
    summary: str,
    success: bool = True,
    model: str = "qwen",
    latency_ms: int = 0,
    error: str = "",
    metadata: dict[str, Any] | None = None,
    count_as_request: bool = False,
    db: Session | None = None,
) -> None:
    """Persist activity in the caller's transaction or an isolated session."""
    if db is not None:
        try:
            append_log(
                db,
                event_type=event_type,
                model=model,
                success=success,
                latency_ms=latency_ms,
                summary=summary,
                error=error,
                metadata=metadata,
                count_as_request=count_as_request,
            )
        except Exception:
            pass
        return

    from app.db.store import session_scope

    try:
        with session_scope() as db:
            append_log(
                db,
                event_type=event_type,
                model=model,
                success=success,
                latency_ms=latency_ms,
                summary=summary,
                error=error,
                metadata=metadata,
                count_as_request=count_as_request,
            )
    except Exception:
        pass  # Never break prep if logging fails


def get_active_analyze_from_logs(db: Session) -> dict[str, Any] | None:
    """Return metadata for an in-progress field-analysis run from recent logs."""
    from datetime import datetime

    logs = get_logs(db, limit=80)
    start_idx = next((i for i, log in enumerate(logs) if log.get("type") == "analyze_start"), None)
    if start_idx is None:
        return None
    start = logs[start_idx]
    start_meta = start.get("metadata") or {}
    app_id = start_meta.get("applicationId")

    for entry in logs[:start_idx]:
        if entry.get("type") in ("analyze_complete", "analyze_failed"):
            entry_meta = entry.get("metadata") or {}
            if not app_id or entry_meta.get("applicationId") in (app_id, None):
                return None
        if entry.get("type") == "analyze_start":
            break

    started_at = start.get("timestamp", "")
    if started_at:
        try:
            t = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            age_sec = (datetime.now(UTC) - t).total_seconds()
            if age_sec > 10 * 60:
                return None
        except (ValueError, TypeError):
            pass

    return {
        "active": True,
        "applicationId": app_id,
        "startedAt": started_at,
        "summary": start.get("summary", ""),
        "companyName": start_meta.get("companyName", ""),
    }


def get_active_prep_from_logs(db: Session) -> dict[str, Any] | None:
    """Return metadata for an in-progress prep run inferred from recent logs."""
    from datetime import datetime

    from app.services.application_assistant.persistence import get_application_draft
    from app.services.application_assistant.qwen_agent import get_agent_run
    from app.services.application_assistant.worker import is_app_locked

    logs = get_logs(db, limit=50)
    start_idx = next((i for i, log in enumerate(logs) if log.get("type") == "agent_prep_start"), None)
    if start_idx is None:
        return None
    start = logs[start_idx]
    for entry in logs[:start_idx]:
        if entry.get("type") in ("agent_prep_complete", "agent_prep_failed", "prep_error", "agent_error"):
            return None

    app_id = (start.get("metadata") or {}).get("applicationId")
    if not app_id:
        return None

    started_at = start.get("timestamp", "")
    if started_at:
        try:
            t = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            age_sec = (datetime.now(UTC) - t).total_seconds()
            if age_sec > 20 * 60:
                return None
        except (ValueError, TypeError):
            pass

    app_id_str = str(app_id)
    draft = get_application_draft(db, app_id_str)
    agent_run = get_agent_run(db, app_id_str)
    if agent_run and agent_run.get("status") == "running":
        pass
    elif draft and draft.get("status") == "in_progress" and is_app_locked(app_id_str):
        pass
    else:
        return None

    return {
        "active": True,
        "applicationId": app_id_str,
        "startedAt": started_at,
        "summary": start.get("summary", ""),
    }


class ActivityTimer:
    """Context manager for timing LLM calls."""

    def __init__(self) -> None:
        self.start = 0.0
        self.elapsed_ms = 0

    def __enter__(self) -> ActivityTimer:
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        self.elapsed_ms = int((time.perf_counter() - self.start) * 1000)
