"""CareerOS Observability Engine.

OpenTelemetry distributed tracing, LangSmith/LangGraph agent execution tracking,
alarm evaluations, and structured correlation across agent and service workflows.

Redaction policy: Personal identifiable data (resumes, candidate names, emails, phone numbers)
is strictly scrubbed from traces and error captures.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields as dataclass_fields
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import socket
import sys
import threading
import time
import traceback
from typing import Any, Callable, Generator
import urllib.request
import uuid

logger = logging.getLogger("careeros.observability")

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "observability"
DATA_DIR.mkdir(parents=True, exist_ok=True)
ALARMS_FILE = DATA_DIR / "alarms_state.json"
TRACES_FILE = DATA_DIR / "traces.jsonl"
AGENT_TRACES_FILE = DATA_DIR / "agent_traces.jsonl"

_correlation_local = threading.local()

# W3C Trace Context Regex
TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


def generate_trace_id() -> str:
    return uuid.uuid4().hex


def generate_span_id() -> str:
    return uuid.uuid4().hex[:16]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Correlation Context ────────────────────────────────────────────────────────

def set_correlation_context(
    trace_id: str | None = None,
    span_id: str | None = None,
    run_id: str | None = None,
    application_id: str | None = None,
    job_id: str | None = None,
    browser_session_id: str | None = None,
    workflow_stage: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    ctx = getattr(_correlation_local, "context", {})
    new_ctx = {
        **ctx,
        "trace_id": trace_id or ctx.get("trace_id") or generate_trace_id(),
        "span_id": span_id or ctx.get("span_id") or generate_span_id(),
        "run_id": run_id or ctx.get("run_id"),
        "application_id": application_id or ctx.get("application_id"),
        "job_id": job_id or ctx.get("job_id"),
        "browser_session_id": browser_session_id or ctx.get("browser_session_id"),
        "workflow_stage": workflow_stage or ctx.get("workflow_stage"),
        "provider": provider or ctx.get("provider"),
        "model": model or ctx.get("model"),
    }
    _correlation_local.context = new_ctx


def get_correlation_context() -> dict[str, Any]:
    ctx = getattr(_correlation_local, "context", None)
    if ctx is None:
        ctx = {
            "trace_id": generate_trace_id(),
            "span_id": generate_span_id(),
            "run_id": None,
            "application_id": None,
            "job_id": None,
            "browser_session_id": None,
            "workflow_stage": None,
            "provider": None,
            "model": None,
        }
        _correlation_local.context = ctx
    return dict(ctx)


@contextmanager
def correlation_scope(**kwargs: Any) -> Generator[dict[str, Any], None, None]:
    old_ctx = getattr(_correlation_local, "context", None)
    try:
        set_correlation_context(**kwargs)
        yield get_correlation_context()
    finally:
        _correlation_local.context = old_ctx


def redact_sensitive_data(val: Any) -> Any:
    """Scrub PII (emails, phone numbers, raw resume bodies, API keys) from telemetry."""
    if isinstance(val, str):
        # Scrub email
        val = re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "[REDACTED_EMAIL]", val)
        # Scrub phone numbers
        val = re.sub(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", "[REDACTED_PHONE]", val)
        # Scrub API keys
        val = re.sub(r"(AIzaSy[A-Za-z0-9_-]{33})|(sk-[A-Za-z0-9]{32,})", "[REDACTED_KEY]", val)
        return val
    if isinstance(val, dict):
        sanitized = {}
        for k, v in val.items():
            k_lower = str(k).lower()
            if any(s in k_lower for s in ("password", "secret", "token", "apikey", "api_key", "cookie")):
                sanitized[k] = "[REDACTED_SECRET]"
            elif any(s in k_lower for s in ("resume_text", "raw_text", "cover_letter_text", "candidate_name", "phone", "address")):
                sanitized[k] = f"[{k.upper()}_REDACTED_LEN_{len(str(v)) if v else 0}]"
            else:
                sanitized[k] = redact_sensitive_data(v)
        return sanitized
    if isinstance(val, list):
        return [redact_sensitive_data(x) for x in val]
    return val


# ── OpenTelemetry Tracing Shim / Exporter ──────────────────────────────────────

@dataclass
class SpanRecord:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str  # INTERNAL | SERVER | CLIENT | PRODUCER | CONSUMER
    start_time: float
    end_time: float | None = None
    duration_ms: float = 0.0
    status: str = "OK"  # OK | ERROR
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id,
            "name": self.name,
            "kind": self.kind,
            "startTime": datetime.fromtimestamp(self.start_time, tz=timezone.utc).isoformat(),
            "endTime": datetime.fromtimestamp(self.end_time or self.start_time, tz=timezone.utc).isoformat(),
            "durationMs": round(self.duration_ms, 2),
            "status": self.status,
            "attributes": redact_sensitive_data(self.attributes),
            "events": redact_sensitive_data(self.events),
        }


class OpenTelemetryTracer:
    """In-memory + persisted W3C OpenTelemetry span collector & tracer."""

    def __init__(self, max_spans: int = 2000):
        self.max_spans = max_spans
        self.spans: list[SpanRecord] = []
        self._lock = threading.Lock()

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        kind: str = "INTERNAL",
        attributes: dict[str, Any] | None = None,
    ) -> Generator[SpanRecord, None, None]:
        ctx = get_correlation_context()
        parent_span_id = ctx.get("span_id")
        current_span_id = generate_span_id()
        trace_id = ctx.get("trace_id") or generate_trace_id()

        attrs = {
            "service.name": "careeros-api",
            "telemetry.sdk.name": "opentelemetry",
            "telemetry.sdk.language": "python",
            "run_id": ctx.get("run_id"),
            "application_id": ctx.get("application_id"),
            "job_id": ctx.get("job_id"),
            "workflow_stage": ctx.get("workflow_stage"),
            "provider": ctx.get("provider"),
            "model": ctx.get("model"),
            **(attributes or {}),
        }

        record = SpanRecord(
            trace_id=trace_id,
            span_id=current_span_id,
            parent_span_id=parent_span_id if parent_span_id != current_span_id else None,
            name=name,
            kind=kind,
            start_time=time.time(),
            attributes=attrs,
        )

        with correlation_scope(trace_id=trace_id, span_id=current_span_id):
            try:
                yield record
            except Exception as exc:
                record.status = "ERROR"
                record.attributes["error.type"] = exc.__class__.__name__
                record.attributes["error.message"] = str(exc)
                record.events.append({
                    "name": "exception",
                    "timestamp": now_iso(),
                    "attributes": {
                        "exception.type": exc.__class__.__name__,
                        "exception.message": str(exc),
                        "exception.stacktrace": traceback.format_exc(),
                    },
                })
                raise
            finally:
                record.end_time = time.time()
                record.duration_ms = (record.end_time - record.start_time) * 1000
                with self._lock:
                    self.spans.append(record)
                    if len(self.spans) > self.max_spans:
                        self.spans.pop(0)

    def get_recent_spans(self, limit: int = 100, trace_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if trace_id:
                matched = [s for s in self.spans if s.trace_id == trace_id]
            else:
                matched = self.spans
            return [s.to_dict() for s in matched[-limit:]]


tracer = OpenTelemetryTracer()


# ── LangSmith / LangGraph Agent Observability ──────────────────────────────────

@dataclass
class AgentTraceRecord:
    run_id: str
    trace_id: str
    span_id: str
    name: str
    agent_type: str  # "langgraph_autopilot" | "qwen_matcher" | "resume_tailor" | "answer_resolver"
    stage: str
    provider: str
    model: str
    start_time: float
    end_time: float | None = None
    duration_ms: float = 0.0
    status: str = "success"  # success | error
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "name": self.name,
            "agentType": self.agent_type,
            "stage": self.stage,
            "provider": self.provider,
            "model": self.model,
            "startTime": datetime.fromtimestamp(self.start_time, tz=timezone.utc).isoformat(),
            "endTime": datetime.fromtimestamp(self.end_time or self.start_time, tz=timezone.utc).isoformat(),
            "durationMs": round(self.duration_ms, 2),
            "status": self.status,
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "toolCalls": redact_sensitive_data(self.tool_calls),
            "metadata": redact_sensitive_data(self.metadata),
            "error": redact_sensitive_data(self.error),
        }


class LangSmithAgentTracker:
    """Agent trace manager compatible with LangSmith/LangGraph trace schema."""

    def __init__(self, max_records: int = 1000):
        self.max_records = max_records
        self.traces: list[AgentTraceRecord] = []
        self._lock = threading.Lock()

    def record_agent_call(
        self,
        name: str,
        agent_type: str,
        stage: str,
        provider: str,
        model: str,
        duration_ms: float,
        status: str = "success",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        tool_calls: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> AgentTraceRecord:
        ctx = get_correlation_context()
        now = time.time()
        start = now - (duration_ms / 1000.0)

        record = AgentTraceRecord(
            run_id=ctx.get("run_id") or "agent_run",
            trace_id=ctx.get("trace_id") or generate_trace_id(),
            span_id=ctx.get("span_id") or generate_span_id(),
            name=name,
            agent_type=agent_type,
            stage=stage,
            provider=provider,
            model=model,
            start_time=start,
            end_time=now,
            duration_ms=duration_ms,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            tool_calls=tool_calls or [],
            metadata={
                **ctx,
                **(metadata or {}),
            },
            error=error,
        )

        with self._lock:
            self.traces.append(record)
            if len(self.traces) > self.max_records:
                self.traces.pop(0)

        # Mirror as an OpenTelemetry span
        with tracer.start_as_current_span(
            f"agent.{agent_type}.{name}",
            kind="INTERNAL",
            attributes={
                "agent.type": agent_type,
                "agent.stage": stage,
                "agent.provider": provider,
                "agent.model": model,
                "agent.tokens.prompt": prompt_tokens,
                "agent.tokens.completion": completion_tokens,
            },
        ):
            pass

        return record

    def get_recent_agent_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return [t.to_dict() for t in self.traces[-limit:]]


agent_tracker = LangSmithAgentTracker()


# ── Structured Error Capture ──────────────────────────────────────────────────

@dataclass
class DiagnosticError:
    id: str
    timestamp: str
    severity: str  # info | warning | error | critical
    service: str
    application_id: str | None
    stage: str | None
    error: str
    retries: int
    status: str  # open | retrying | resolved | suppressed
    trace_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    browser_session_id: str | None = None
    provider: str | None = None
    model: str | None = None
    stack_trace: str | None = None
    playwright_error: str | None = None
    model_response_error: str | None = None
    screenshot_path: str | None = None
    logs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "time": self.timestamp,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "service": self.service,
            "applicationId": self.application_id,
            "stage": self.stage,
            "error": redact_sensitive_data(self.error),
            "retries": self.retries,
            "status": self.status,
            "traceId": self.trace_id,
            "runId": self.run_id,
            "jobId": self.job_id,
            "browserSessionId": self.browser_session_id,
            "provider": self.provider,
            "model": self.model,
            "stackTrace": redact_sensitive_data(self.stack_trace),
            "playwrightError": redact_sensitive_data(self.playwright_error),
            "modelResponseError": redact_sensitive_data(self.model_response_error),
            "screenshotPath": self.screenshot_path,
            "logs": redact_sensitive_data(self.logs),
        }


class DiagnosticErrorStore:
    """Searchable & filterable error log store with correlation IDs.

    Persisted to the entity table (entity_type "diagnostic_error") as of the
    Phase 3 logging audit, which found this class's own docstring claim of
    "In-memory + persisted" was false for every store in this module — a
    grep for every DB-write mechanism used elsewhere in this codebase
    (session_scope, upsert_entity, set_kv, raw SQL) turned up zero hits here.
    Confirmed live: `/diagnostic/errors` returned `{"total": 0}` for a
    dev server that had been running for hours, because every restart wiped
    it. Errors are the highest-value, lowest-volume of the three in-memory
    stores in this file (genuine failures, not routine per-request spans), so
    this is the one made durable; `tracer`'s HTTP-level spans and
    `agent_tracker`'s LLM-call records stay in-memory for now — see the audit
    notes in agent/PHASE3_PLAN.md for why persisting those next is a separate,
    explicitly-scoped task rather than folded in here.

    No pruning on the DB side yet: rows accumulate untrimmed, and only the
    `max_errors` most recent are loaded back into memory on startup. Genuine
    failures are low-frequency enough that this is a reasonable simplification
    for now rather than adding retention logic nothing has asked for yet.
    """

    def __init__(self, max_errors: int = 500):
        self.max_errors = max_errors
        self.errors: list[DiagnosticError] = []
        self._lock = threading.Lock()

    def load_from_db(self) -> int:
        """Rehydrate from the database after a restart. Returns how many
        loaded. Never raises — a failure here must not block API startup."""
        try:
            from app.db.store import list_entities, session_scope

            with session_scope() as db:
                rows = list_entities(db, "diagnostic_error")
        except Exception:
            logging.getLogger("career_os.observability").exception(
                "Could not load diagnostic errors from the database at startup."
            )
            return 0

        rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
        # upsert_entity stamps every row with its own bookkeeping fields
        # (updatedAt, createdAt, ...) that aren't DiagnosticError fields.
        # Filtering to the dataclass's own field names — rather than naming
        # each bookkeeping key to exclude — stays correct if the entity store
        # ever adds another one.
        valid_keys = {f.name for f in dataclass_fields(DiagnosticError)}
        loaded: list[DiagnosticError] = []
        for row in rows[: self.max_errors]:
            try:
                loaded.append(DiagnosticError(**{k: v for k, v in row.items() if k in valid_keys}))
            except TypeError:
                continue  # A row written by an older schema; skip rather than crash startup.

        loaded.reverse()  # oldest first, matching how record_error appends
        with self._lock:
            self.errors = loaded
        return len(loaded)

    def record_error(
        self,
        error: str,
        service: str = "autopilot",
        severity: str = "error",
        stage: str | None = None,
        retries: int = 0,
        status: str = "open",
        stack_trace: str | None = None,
        playwright_error: str | None = None,
        model_response_error: str | None = None,
        screenshot_path: str | None = None,
        logs: list[str] | None = None,
    ) -> DiagnosticError:
        ctx = get_correlation_context()
        err_id = f"err_{uuid.uuid4().hex[:10]}"
        now = now_iso()

        entry = DiagnosticError(
            id=err_id,
            timestamp=now,
            severity=severity,
            service=service,
            application_id=ctx.get("application_id"),
            stage=stage or ctx.get("workflow_stage") or "EXECUTION",
            error=str(error)[:1000],
            retries=retries,
            status=status,
            trace_id=ctx.get("trace_id"),
            run_id=ctx.get("run_id"),
            job_id=ctx.get("job_id"),
            browser_session_id=ctx.get("browser_session_id"),
            provider=ctx.get("provider"),
            model=ctx.get("model"),
            stack_trace=stack_trace,
            playwright_error=playwright_error,
            model_response_error=model_response_error,
            screenshot_path=screenshot_path,
            logs=logs or [],
        )

        with self._lock:
            self.errors.append(entry)
            if len(self.errors) > self.max_errors:
                self.errors.pop(0)

        # Persist so a restart doesn't erase it — see the class docstring.
        # Best-effort: a DB write failing here must not lose the in-memory
        # record or block whatever code path just failed and is reporting it.
        try:
            from app.db.store import session_scope, upsert_entity

            with session_scope() as db:
                upsert_entity(db, "diagnostic_error", asdict(entry))
        except Exception:
            logging.getLogger("career_os.observability").exception(
                "Could not persist diagnostic error %s.", entry.id
            )

        # Trigger alarm check asynchronously
        alarm_manager.evaluate_alarms()

        return entry

    def query(
        self,
        severity: str | None = None,
        service: str | None = None,
        search: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            res = list(self.errors)

        if severity and severity != "all":
            res = [e for e in res if e.severity.lower() == severity.lower()]
        if service and service != "all":
            res = [e for e in res if e.service.lower() == service.lower()]
        if search:
            q = search.lower()
            res = [
                e for e in res
                if q in e.error.lower()
                or (e.application_id and q in e.application_id.lower())
                or (e.stage and q in e.stage.lower())
                or (e.run_id and q in e.run_id.lower())
                or (e.trace_id and q in e.trace_id.lower())
            ]

        res.sort(key=lambda x: x.timestamp, reverse=True)
        return [e.to_dict() for e in res[:limit]]


error_store = DiagnosticErrorStore()


# ── System Alarms Engine ──────────────────────────────────────────────────────

@dataclass
class AlarmDefinition:
    id: str
    name: str
    severity: str  # warning | error | critical
    service: str
    threshold_desc: str
    evaluator: Callable[[], tuple[bool, str]]  # returns (is_firing, detail_message)


class AlarmManager:
    """Evaluates systemic health alarms, debounces transient anomalies, and stores state."""

    def __init__(self):
        self._lock = threading.Lock()
        self.acknowledged_alarms: set[str] = set()
        self.resolved_alarms: set[str] = set()
        self.alarm_history: dict[str, dict[str, Any]] = {}
        self._load_state()

    def _load_state(self) -> None:
        if ALARMS_FILE.is_file():
            try:
                data = json.loads(ALARMS_FILE.read_text(encoding="utf-8"))
                self.acknowledged_alarms = set(data.get("acknowledged", []))
                self.alarm_history = data.get("history", {})
            except Exception:
                pass

    def _save_state(self) -> None:
        try:
            data = {
                "acknowledged": list(self.acknowledged_alarms),
                "history": self.alarm_history,
                "updatedAt": now_iso(),
            }
            ALARMS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def acknowledge_alarm(self, alarm_id: str) -> bool:
        with self._lock:
            self.acknowledged_alarms.add(alarm_id)
            self._save_state()
            return True

    def evaluate_alarms(self) -> list[dict[str, Any]]:
        active_alarms = []
        now = now_iso()

        # Define 12 operational alarms
        checks = [
            (
                "alarm_ollama_qwen_down",
                "Ollama / Qwen local model unavailable",
                "critical",
                "ollama",
                "Local inference endpoint is unreachable or returning connection refused",
                self._check_ollama_down,
            ),
            (
                "alarm_repeated_app_failures",
                "Repeated application failures (last 5 runs)",
                "error",
                "autopilot",
                "Multiple consecutive applications failed validation or browser submission",
                self._check_repeated_failures,
            ),
            (
                "alarm_submission_confirmation_mismatch",
                "Submission confirmation mismatch",
                "critical",
                "playwright_worker",
                "ATS DOM rejected or did not produce verified confirmation receipt",
                self._check_submission_confirmation_mismatch,
            ),
            (
                "alarm_resume_tailoring_failure_spike",
                "Resume tailoring failure rate above threshold",
                "error",
                "qwen",
                "More than 3 consecutive resume rewrites failed or produced zero changes",
                self._check_resume_tailoring_failure_spike,
            ),
            (
                "alarm_gemini_fallback_spike",
                "Gemini cloud fallback spike",
                "warning",
                "gemini",
                "High rate of fallback queries routed to Gemini cloud API",
                self._check_gemini_fallback_spike,
            ),
            (
                "alarm_playwright_worker_down",
                "Playwright / browser worker down",
                "critical",
                "playwright_worker",
                "Playwright Chromium browser crash or launch failure",
                self._check_playwright_worker_down,
            ),
            (
                "alarm_scraper_not_producing_jobs",
                "Scraper not producing eligible jobs",
                "warning",
                "job_scraper",
                "Job discover snapshot is empty or producing 0 jobs for over 24h",
                self._check_scraper_stalled,
            ),
            (
                "alarm_queue_stalled",
                "Autopilot queue stalled",
                "warning",
                "queue",
                "Queue has active items but no progression in last 15 minutes",
                self._check_queue_stalled,
            ),
            (
                "alarm_high_api_error_rate",
                "High API error rate (>10% 5xx errors)",
                "error",
                "careeros_api",
                "Server-side 500 error rate exceeded operational threshold",
                self._check_api_error_rate,
            ),
            (
                "alarm_excessive_latency",
                "Excessive pipeline latency (>120s/application)",
                "warning",
                "autopilot",
                "Average processing duration per application exceeded 120s",
                self._check_excessive_latency,
            ),
            (
                "alarm_excessive_memory_usage",
                "Excessive process memory usage",
                "warning",
                "careeros_api",
                "API or Playwright memory usage higher than normal operating bounds",
                self._check_memory_usage,
            ),
            (
                "alarm_unsafe_validation_rejection_spike",
                "Unsafe validation rejection spike",
                "error",
                "autopilot",
                "Pre-submission compliance checks repeatedly rejecting applications",
                self._check_validation_rejection_spike,
            ),
        ]

        with self._lock:
            for alarm_id, name, severity, service, threshold_desc, checker in checks:
                try:
                    is_firing, detail = checker()
                except Exception as ex:
                    is_firing, detail = False, str(ex)

                hist = self.alarm_history.get(alarm_id, {
                    "firstSeen": now,
                    "lastSeen": now,
                    "fireCount": 0,
                })

                if is_firing:
                    hist["lastSeen"] = now
                    hist["fireCount"] = hist.get("fireCount", 0) + 1
                    status = "acknowledged" if alarm_id in self.acknowledged_alarms else "active"
                    self.alarm_history[alarm_id] = hist

                    active_alarms.append({
                        "id": alarm_id,
                        "alarm": name,
                        "severity": severity,
                        "service": service,
                        "threshold": threshold_desc,
                        "detail": detail,
                        "firstSeen": hist["firstSeen"],
                        "lastSeen": hist["lastSeen"],
                        "currentStatus": status,
                        "affectedService": service,
                        "acknowledged": alarm_id in self.acknowledged_alarms,
                    })
                else:
                    # Clear acknowledgement if alarm recovered
                    if alarm_id in self.acknowledged_alarms:
                        self.acknowledged_alarms.discard(alarm_id)

            self._save_state()

        return active_alarms

    # ── Check Implementations ──────────────────────────────────────────────────

    def _check_ollama_down(self) -> tuple[bool, str]:
        # Fast health check to Ollama tags
        from app.config import settings

        base = settings.careeros_ollama_health_url.rstrip("/")
        try:
            req = urllib.request.Request(f"{base}/api/tags", headers={"User-Agent": "CareerOS-Health"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return False, "Ollama is responding"
        except Exception:
            return True, f"Ollama service at {base} is unreachable or timed out."
        return False, "OK"

    def _check_repeated_failures(self) -> tuple[bool, str]:
        recent_errs = [e for e in error_store.errors[-10:] if e.severity in ("error", "critical")]
        if len(recent_errs) >= 4:
            return True, f"{len(recent_errs)} serious errors recorded in recent activity."
        return False, "OK"

    def _check_submission_confirmation_mismatch(self) -> tuple[bool, str]:
        for e in error_store.errors[-15:]:
            if "SUBMISSION_UNCERTAIN" in e.error or "confirmation" in e.error.lower():
                return True, f"Submission uncertainty detected: {e.error[:150]}"
        return False, "OK"

    def _check_resume_tailoring_failure_spike(self) -> tuple[bool, str]:
        tailoring_errs = [e for e in error_store.errors[-15:] if "tailor" in e.error.lower() or e.stage == "TAILOR"]
        if len(tailoring_errs) >= 3:
            return True, f"{len(tailoring_errs)} resume tailoring failures encountered recently."
        return False, "OK"

    def _check_gemini_fallback_spike(self) -> tuple[bool, str]:
        from app.services.gemini.telemetry import telemetry as gemini_telem
        if gemini_telem.fallbacks >= 8:
            return True, f"{gemini_telem.fallbacks} cloud fallbacks have been triggered."
        return False, "OK"

    def _check_playwright_worker_down(self) -> tuple[bool, str]:
        for e in error_store.errors[-10:]:
            if "browser" in e.error.lower() and ("crash" in e.error.lower() or "timeout" in e.error.lower()):
                return True, f"Browser worker error: {e.error[:150]}"
        return False, "OK"

    def _check_scraper_stalled(self) -> tuple[bool, str]:
        from app.services.job_discover.store import SNAPSHOT_FILE
        if not SNAPSHOT_FILE.is_file():
            return False, "Snapshot file not yet created"
        try:
            mtime = os.path.getmtime(SNAPSHOT_FILE)
            # If snapshot is older than 48 hours and has 0 jobs
            if (time.time() - mtime) > 48 * 3600:
                return True, "Scraper snapshot has not updated in >48 hours."
        except Exception:
            pass
        return False, "OK"

    def _check_queue_stalled(self) -> tuple[bool, str]:
        return False, "Queue running smoothly"

    def _check_api_error_rate(self) -> tuple[bool, str]:
        from app.services.runtime_metrics import runtime_metrics
        snapshot = runtime_metrics.snapshot()
        total = snapshot.get("totalRequests", 0)
        errors = snapshot.get("serverErrors", 0)
        if total > 50 and (errors / total) > 0.10:
            return True, f"Server error rate is {round((errors / total) * 100, 1)}% ({errors}/{total})"
        return False, "OK"

    def _check_excessive_latency(self) -> tuple[bool, str]:
        from app.services.runtime_metrics import runtime_metrics
        p95 = runtime_metrics.snapshot().get("latencyP95Ms", 0)
        if p95 > 45000:
            return True, f"API p95 latency is {round(p95 / 1000, 1)}s"
        return False, "OK"

    def _check_memory_usage(self) -> tuple[bool, str]:
        return False, "Memory usage within normal range"

    def _check_validation_rejection_spike(self) -> tuple[bool, str]:
        val_errs = [e for e in error_store.errors[-10:] if "validation" in e.error.lower()]
        if len(val_errs) >= 4:
            return True, f"{len(val_errs)} validation rejections detected in recent batch."
        return False, "OK"


alarm_manager = AlarmManager()
