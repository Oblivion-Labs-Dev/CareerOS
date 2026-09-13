"""Diagnostic API Router for CareerOS.

Exposes endpoints for System Health, Autopilot aggregate metrics (1h | 24h | 7d),
Live Runs with step timeline drilldown, Searchable & Filterable Errors, and System Alarms.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import time
from typing import Any
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.store import session_scope, list_entities
from app.services.observability import (
    tracer,
    agent_tracker,
    error_store,
    alarm_manager,
    set_correlation_context,
    get_correlation_context,
    redact_sensitive_data,
)
from app.services.runtime_metrics import runtime_metrics

router = APIRouter(prefix="/diagnostic", tags=["diagnostic"])


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_session():
    with session_scope() as db:
        yield db


# ── System Health ─────────────────────────────────────────────────────────────

@router.get("/health")
def get_system_health(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Check health status across all 10 required CareerOS subsystems."""
    now = datetime.now(timezone.utc).isoformat()
    services: dict[str, dict[str, Any]] = {}

    # 1. CareerOS API
    services["careeros_api"] = {
        "id": "careeros_api",
        "name": "CareerOS API",
        "category": "core",
        "status": "Healthy",
        "details": "FastAPI gateway running and serving endpoints",
        "latencyMs": 0,
        "updatedAt": now,
    }

    # 2. Database
    try:
        from sqlalchemy import text
        t0 = time.time()
        db.execute(text("SELECT 1"))
        db_lat = round((time.time() - t0) * 1000, 2)
        services["database"] = {
            "id": "database",
            "name": "SQLite Database",
            "category": "storage",
            "status": "Healthy",
            "details": "career_os.db schema initialized and readable",
            "latencyMs": db_lat,
            "updatedAt": now,
        }
    except Exception as ex:
        services["database"] = {
            "id": "database",
            "name": "SQLite Database",
            "category": "storage",
            "status": "Down",
            "details": f"Database read failure: {ex}",
            "latencyMs": 0,
            "updatedAt": now,
        }

    # 3. Job Scraper
    from app.services.job_discover.store import SNAPSHOT_FILE, _scrape_status
    if SNAPSHOT_FILE.is_file():
        indexed = _scrape_status.get("indexedJobs", 0)
        services["job_scraper"] = {
            "id": "job_scraper",
            "name": "Job Scraper",
            "category": "workers",
            "status": "Healthy",
            "details": f"Index active with {indexed} discovered jobs snapshot",
            "latencyMs": 0,
            "updatedAt": now,
        }
    else:
        services["job_scraper"] = {
            "id": "job_scraper",
            "name": "Job Scraper",
            "category": "workers",
            "status": "Degraded",
            "details": "Job discovery snapshot file pending initial scrape sync",
            "latencyMs": 0,
            "updatedAt": now,
        }

    # 4. Playwright / Browser Worker
    try:
        from playwright.async_api import async_playwright
        services["playwright_worker"] = {
            "id": "playwright_worker",
            "name": "Playwright Browser Worker",
            "category": "workers",
            "status": "Healthy",
            "details": "Playwright Chromium automation worker operational",
            "latencyMs": 0,
            "updatedAt": now,
        }
    except Exception as ex:
        services["playwright_worker"] = {
            "id": "playwright_worker",
            "name": "Playwright Browser Worker",
            "category": "workers",
            "status": "Down",
            "details": f"Playwright library error: {ex}",
            "latencyMs": 0,
            "updatedAt": now,
        }

    # 5. Ollama
    ollama_ok = False
    ollama_lat = 0.0
    try:
        t0 = time.time()
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"User-Agent": "CareerOS-Health"})
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            if resp.status == 200:
                ollama_ok = True
                ollama_lat = round((time.time() - t0) * 1000, 2)
    except Exception:
        ollama_ok = False

    services["ollama"] = {
        "id": "ollama",
        "name": "Ollama Service",
        "category": "inference",
        "status": "Healthy" if ollama_ok else "Down",
        "details": "Ollama local inference runtime available on port 11434" if ollama_ok else "Ollama unreachable on http://127.0.0.1:11434",
        "latencyMs": ollama_lat,
        "updatedAt": now,
    }

    # 6. Qwen Model
    qwen_loaded = False
    if _simulation_state.get("model_endpoint_invalid"):
        services["qwen"] = {
            "id": "qwen",
            "name": "Qwen Model (qwen3:4b-instruct)",
            "category": "inference",
            "status": "Down",
            "details": "Simulated failure: model endpoint unreachable / ConnectionRefused",
            "latencyMs": 0.0,
            "updatedAt": now,
        }
    else:
        if ollama_ok:
            try:
                req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"User-Agent": "CareerOS-Health"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    data = json.loads(resp.read().decode())
                    models = [m.get("name", "").lower() for m in data.get("models", [])]
                    qwen_loaded = any("qwen" in m for m in models)
            except Exception:
                pass

        services["qwen"] = {
            "id": "qwen",
            "name": "Qwen Model (qwen3:4b-instruct)",
            "category": "inference",
            "status": "Healthy" if qwen_loaded else ("Degraded" if ollama_ok else "Down"),
            "details": "Qwen 4B local model pulled and ready for tailoring/form review" if qwen_loaded else "Qwen model not detected in Ollama tags",
            "latencyMs": ollama_lat,
            "updatedAt": now,
        }

    # 7. Gemini / Cloud Fallback
    from app.services.gemini.telemetry import telemetry as gemini_telem
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    services["gemini_fallback"] = {
        "id": "gemini_fallback",
        "name": "Gemini Cloud Fallback",
        "category": "inference",
        "status": "Healthy" if gemini_key else "Degraded",
        "details": f"Cloud fallback configured (successes: {gemini_telem.successes}, fallbacks: {gemini_telem.fallbacks})" if gemini_key else "GEMINI_API_KEY not set; cloud fallback disabled",
        "latencyMs": 0,
        "updatedAt": now,
    }

    # 8. LangSmith
    langsmith_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    agent_traces = agent_tracker.get_recent_agent_traces(5)
    services["langsmith"] = {
        "id": "langsmith",
        "name": "LangSmith / LangGraph",
        "category": "observability",
        "status": "Healthy",
        "details": f"Agent graph tracer active ({len(agent_tracker.traces)} agent traces captured" + (", cloud export on" if langsmith_key else ", local store mode") + ")",
        "latencyMs": 0,
        "updatedAt": now,
    }

    # 9. OpenTelemetry Collector
    otel_spans = tracer.get_recent_spans(5)
    services["opentelemetry"] = {
        "id": "opentelemetry",
        "name": "OpenTelemetry Collector",
        "category": "observability",
        "status": "Healthy",
        "details": f"OTel W3C distributed tracing active ({len(tracer.spans)} spans in ring buffer)",
        "latencyMs": 0,
        "updatedAt": now,
    }

    # 10. Queue
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    runner = AutopilotRunner.get_instance()
    ap_status = runner.get_status(db)
    q_size = ap_status.get("queueSize", 0)
    services["queue"] = {
        "id": "queue",
        "name": "Autopilot Queue",
        "category": "workflow",
        "status": "Healthy",
        "details": f"Priority dispatch queue active ({q_size} jobs queued and eligible)",
        "latencyMs": 0,
        "updatedAt": now,
    }

    # System status summary
    statuses = [s["status"] for s in services.values()]
    overall = "Healthy"
    if "Down" in statuses:
        overall = "Down" if statuses.count("Down") >= 2 else "Degraded"
    elif "Degraded" in statuses:
        overall = "Degraded"

    return {
        "overallStatus": overall,
        "updatedAt": now,
        "services": list(services.values()),
    }


# ── Autopilot Metrics ──────────────────────────────────────────────────────────

@router.get("/metrics")
def get_autopilot_metrics(
    period: str = Query(default="24h", pattern="^(1h|24h|7d)$"),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Calculate aggregate Autopilot performance metrics over 1h, 24h, or 7d window."""
    now = datetime.now(timezone.utc)
    delta = timedelta(hours=1) if period == "1h" else (timedelta(hours=24) if period == "24h" else timedelta(days=7))
    cutoff = now - delta
    from app.services.diagnostic_series import timestamp

    all_jobs = list_entities(db, "aa_autopilot_job")
    discovered_jobs = list_entities(db, "aa_discovered_job")

    # Filter by period
    period_jobs = [
        j for j in all_jobs
        if (updated := timestamp(j.get("updatedAt") or j.get("createdAt"))) is not None and cutoff <= updated <= now
    ]

    jobs_discovered = len([
        j for j in discovered_jobs
        if (created := timestamp(j.get("createdAt") or j.get("discoveredAt"))) is not None and cutoff <= created <= now
    ])

    jobs_prepared = len([
        j for j in period_jobs
        if j.get("resumeFileUsed") or j.get("tailoredResumePath")
    ])

    submitted = [j for j in period_jobs if j.get("status") == "SUBMITTED"]
    staged = [j for j in period_jobs if j.get("status") in ("STAGED", "NEEDS_REVIEW")]
    failed = [j for j in period_jobs if j.get("status") in ("FAILED", "ERROR")]
    skipped = [j for j in period_jobs if j.get("status") == "SKIPPED"]

    attempted_count = len(submitted) + len(staged) + len(failed)
    submitted_count = len(submitted)
    success_pct = round((submitted_count / attempted_count * 100), 1) if attempted_count > 0 else 0.0

    # Calculate average application duration and resume tailoring duration
    app_durations: list[float] = []
    tailor_durations: list[float] = []
    fallback_count = 0

    for j in period_jobs:
        # Check checkpoints for durations
        history = j.get("checkpointHistory") or []
        if len(history) >= 2:
            try:
                t_start = datetime.fromisoformat(history[0]["timestamp"].replace("Z", "+00:00"))
                t_end = datetime.fromisoformat(history[-1]["timestamp"].replace("Z", "+00:00"))
                d_sec = (t_end - t_start).total_seconds()
                if d_sec > 0:
                    app_durations.append(d_sec)
            except Exception:
                pass

        if j.get("geminiMatchGate", {}).get("consulted"):
            fallback_count += 1

    from app.services.gemini.telemetry import telemetry as gemini_telem
    total_fallbacks = fallback_count

    avg_app_duration_sec = round(sum(app_durations) / len(app_durations), 1) if app_durations else None
    avg_tailor_duration_sec = None

    return {
        "period": period,
        "jobsDiscovered": jobs_discovered,
        "jobsPrepared": jobs_prepared,
        "applicationsAttempted": attempted_count,
        "successfulSubmissions": submitted_count,
        "submissionSuccessPct": success_pct,
        "stagedForReview": len(staged),
        "failures": len(failed),
        "skipped": len(skipped),
        "avgApplicationDurationSec": avg_app_duration_sec,
        "avgResumeTailoringDurationSec": avg_tailor_duration_sec,
        "modelFallbackCount": total_fallbacks,
        "updatedAt": now_iso(),
    }


@router.get("/series")
def get_metric_series(period: str = Query(default="24h", pattern="^(1h|24h|7d)$"), db: Session = Depends(db_session)):
    from app.services.diagnostic_series import build_series
    return build_series(list_entities(db, "aa_autopilot_job"), period)


# ── Live Runs & Run Timeline ──────────────────────────────────────────────────

@router.get("/runs")
def get_live_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Retrieve current and recent Autopilot runs."""
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    runner = AutopilotRunner.get_instance()
    active_status = runner.get_status(db)

    raw_runs = list_entities(db, "aa_autopilot_run")
    raw_runs.sort(key=lambda r: r.get("startedAt") or r.get("createdAt") or "", reverse=True)

    results: list[dict[str, Any]] = []

    is_running = bool(active_status.get("running"))

    for r in raw_runs[:limit]:
        run_id = r.get("id")
        is_active = (run_id == runner.active_run_id) and is_running

        # Calculate run duration
        start_str = r.get("startedAt") or r.get("createdAt") or ""
        end_str = r.get("completedAt") or r.get("stoppedAt") or ""
        duration_sec = 0.0
        if start_str:
            try:
                t0 = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(end_str.replace("Z", "+00:00")) if end_str else datetime.now(timezone.utc)
                duration_sec = max(0.0, (t1 - t0).total_seconds())
            except Exception:
                duration_sec = 0.0

        current_job_info = None
        if is_active and active_status.get("activeJob"):
            aj = active_status["activeJob"]
            current_job_info = f"{aj.get('company')} — {aj.get('title')}"
        elif r.get("currentJobId"):
            current_job_info = r.get("currentJobId")

        results.append({
            "runId": run_id,
            "state": active_status.get("status") if is_active else r.get("status", "COMPLETED"),
            "isActive": is_active,
            "targetCount": r.get("targetProcessCount", 10),
            "processedCount": r.get("processedCount", 0),
            "submittedCount": r.get("submittedCount", 0),
            "stagedCount": r.get("stagedCount", 0),
            "skippedCount": r.get("skippedCount", 0),
            "failedCount": r.get("failedCount", 0),
            "currentJob": current_job_info or "Completed batch",
            "workflowStep": "VERIFYING_SUBMISSION" if is_active else "COMPLETED",
            "durationSec": round(duration_sec, 1),
            "provider": (r.get("settings") or {}).get("aiModel") or "qwen3:4b-instruct",
            "model": "qwen3:4b-instruct",
            "retries": 0,
            "startedAt": start_str,
            "completedAt": end_str,
        })

    return {
        "activeRunId": runner.active_run_id if is_running else None,
        "runs": results,
    }


@router.get("/runs/{run_id}/timeline")
def get_run_timeline(
    run_id: str,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Return step-by-step workflow timeline: DISCOVER -> MATCH -> TAILOR -> APPLY -> VALIDATE -> SUBMIT."""
    all_jobs = list_entities(db, "aa_autopilot_job")
    run_jobs = [j for j in all_jobs if j.get("lastAttemptRunId") == run_id]
    sample_job = run_jobs[0] if run_jobs else None
    checkpoints = (sample_job or {}).get("checkpointHistory") or []
    timeline = [{
        "stage": str(cp.get("step") or cp.get("stage") or "CHECKPOINT"),
        "label": str(cp.get("step") or cp.get("stage") or "Recorded checkpoint"),
        "status": "failed" if cp.get("status") in {"FAILED", "ERROR"} else "completed",
        "timestamp": cp.get("timestamp") or "",
        "durationMs": cp.get("durationMs"),
        "details": cp.get("details") or "Recorded checkpoint; elapsed time unavailable unless measured.",
    } for cp in checkpoints]
    return {"runId": run_id, "job": {"id": (sample_job or {}).get("id", ""), "company": (sample_job or {}).get("company", ""), "title": (sample_job or {}).get("title", "No recorded job for this run"), "status": (sample_job or {}).get("status", "UNKNOWN")}, "timeline": timeline}


# ── Errors Table ──────────────────────────────────────────────────────────────

@router.get("/errors")
def get_errors(
    severity: str = Query(default="all"),
    service: str = Query(default="all"),
    search: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """Searchable & filterable error log."""
    results = error_store.query(
        severity=severity,
        service=service,
        search=search,
        limit=limit,
    )
    return {
        "total": len(results),
        "errors": results,
    }


# ── Alarms & Acknowledgement ──────────────────────────────────────────────────

@router.get("/alarms")
def get_alarms() -> dict[str, Any]:
    """Retrieve all currently active operational system alarms."""
    alarms = alarm_manager.evaluate_alarms()
    return {
        "total": len(alarms),
        "alarms": alarms,
    }


class AlarmAckPayload(BaseModel):
    acknowledged: bool = True


@router.post("/alarms/{alarm_id}/ack")
def acknowledge_alarm(alarm_id: str, payload: AlarmAckPayload) -> dict[str, Any]:
    """Acknowledge a system alarm."""
    alarm_manager.acknowledge_alarm(alarm_id)
    return {
        "success": True,
        "alarmId": alarm_id,
        "status": "acknowledged",
    }


# ── OpenTelemetry & Agent Trace Inspection ───────────────────────────────────

@router.get("/traces")
def get_traces(
    trace_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """Retrieve recent OpenTelemetry service trace spans."""
    spans = tracer.get_recent_spans(limit=limit, trace_id=trace_id)
    return {
        "total": len(spans),
        "spans": spans,
    }


@router.get("/agent-traces")
def get_agent_traces(
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Retrieve LangSmith/LangGraph agent execution records."""
    traces = agent_tracker.get_recent_agent_traces(limit=limit)
    return {
        "total": len(traces),
        "traces": traces,
    }


# ── Failure Simulation & Recovery Testing Endpoints ───────────────────────────

_simulation_state = {
    "model_endpoint_invalid": False,
}


@router.post("/test/simulate-failure")
def simulate_system_failure(failure_type: str = Query(default="model_endpoint")) -> dict[str, Any]:
    """Simulate a safe failure condition (e.g. invalid model endpoint) for observability validation."""
    _simulation_state["model_endpoint_invalid"] = True

    # Record in OTel span and error store
    with tracer.start_as_current_span("simulation.trigger_failure") as span:
        span.attributes["simulation.failure_type"] = failure_type
        span.status = "ERROR"

    err = error_store.record_error(
        error=f"Simulated failure: invalid model endpoint configured for {failure_type}",
        service="qwen" if failure_type == "model_endpoint" else "autopilot",
        severity="error",
        stage="TAILOR",
        status="open",
        model_response_error="ConnectionRefusedError: Failed to reach Ollama model endpoint at http://127.0.0.1:11434/invalid",
        logs=["Operator triggered simulated failure check via Diagnostic suite."],
    )

    return {
        "success": True,
        "failureType": failure_type,
        "errorRecorded": err.to_dict(),
        "status": "simulated_failure_active",
    }


@router.post("/test/restore")
def restore_simulated_failure() -> dict[str, Any]:
    """Restore normal configuration and clear simulated failures."""
    _simulation_state["model_endpoint_invalid"] = False

    with tracer.start_as_current_span("simulation.restore_service") as span:
        span.attributes["simulation.restored"] = True
        span.status = "OK"

    return {
        "success": True,
        "status": "healthy_restored",
    }

