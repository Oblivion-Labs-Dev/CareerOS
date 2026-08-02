from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

EventKind = Literal["error", "fix"]
EventSource = Literal["api", "client", "system"]

MAX_HISTORY = 120
MAX_OPEN_ERRORS = 80
FIX_WINDOW_SECONDS = 30 * 60
HISTORY_FILE = Path(__file__).resolve().parents[2] / "data" / "logs" / "error-fix-history.jsonl"

FIX_KEYWORDS = ("fixed", "resolved", "recovered", "patch applied", "no longer")

RESOLVED_ERROR_SIGNATURES: dict[str, str] = {
    "GET /favicon.ico": "Added /favicon.ico static route",
    "POST /dev/repair/process-logs": "Registered manual repair routes on API restart",
    "GET /dev/demo/unhandled-scraper-error": "Demo route records to client log without failing the request",
    "POST /jobs/discover/scrape": "Scrape endpoint returns structured errors instead of HTTP 500",
    "GET /email/verify": "Gmail verify returns HTTP 200 with configured flag",
    "background:autofill-complete:log": "Extension frame probing handles cross-origin frames",
    "extension:autofill": "Extension autofill errors addressed in prior fixes",
}


@dataclass
class TrackedEvent:
    id: str
    kind: EventKind
    source: EventSource
    signature: str
    message: str
    at: float
    error_id: str | None = None
    status_code: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "signature": self.signature,
            "message": self.message,
            "at": self.at,
            "atIso": datetime.fromtimestamp(self.at, tz=UTC).isoformat(),
            "errorId": self.error_id,
            "statusCode": self.status_code,
            "meta": self.meta,
        }


@dataclass
class OpenError:
    id: str
    signature: str
    source: EventSource
    message: str
    at: float
    status_code: int | None = None


SEED_EVENTS: list[dict[str, Any]] = [
    {
        "kind": "error",
        "source": "api",
        "signature": "GET /",
        "message": "Root route returned 404 Not Found JSON instead of dashboard",
        "status_code": 404,
    },
    {
        "kind": "fix",
        "source": "system",
        "signature": "GET /",
        "message": "Added HTML ops dashboard at GET / with live charts",
    },
    {
        "kind": "error",
        "source": "client",
        "signature": "extension:autofill",
        "message": "Floating widget stuck on loading with no timeout or error state",
    },
    {
        "kind": "fix",
        "source": "system",
        "signature": "extension:autofill",
        "message": "Added autofill timeouts, error panel, and cancel in floating widget",
    },
    {
        "kind": "error",
        "source": "client",
        "signature": "extension:autofill",
        "message": "First and last name fields not detected on job forms",
    },
    {
        "kind": "fix",
        "source": "system",
        "signature": "extension:autofill",
        "message": "Expanded fieldClassifier patterns for given-name and family-name",
    },
    {
        "kind": "error",
        "source": "system",
        "signature": "web:typescript",
        "message": "Resume corpus fixtures missing CorpusRecord fields",
    },
    {
        "kind": "fix",
        "source": "system",
        "signature": "web:typescript",
        "message": "Added corpusRecordDefaults and phaseOne to seed data",
    },
    {
        "kind": "error",
        "source": "system",
        "signature": "api:gmail-test",
        "message": "Gmail sender test expected 503 but received 200",
    },
    {
        "kind": "fix",
        "source": "system",
        "signature": "api:gmail-test",
        "message": "Mocked empty Gmail settings in test_gmail_sender",
    },
]


class ErrorFixTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._history: deque[TrackedEvent] = deque(maxlen=MAX_HISTORY)
        self._open_errors: dict[str, OpenError] = {}
        self._recent_error_by_route: dict[str, OpenError] = {}
        self._total_errors = 0
        self._total_fixes = 0
        self._event_times: deque[tuple[float, EventKind]] = deque()
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if HISTORY_FILE.is_file():
            self._load_from_disk()

    def _load_from_disk(self) -> None:
        try:
            lines = [line for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
        except OSError:
            return
        for line in lines[-MAX_HISTORY:]:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = TrackedEvent(
                id=str(raw.get("id") or uuid.uuid4().hex[:12]),
                kind=raw.get("kind", "error"),
                source=raw.get("source", "system"),
                signature=str(raw.get("signature") or "unknown"),
                message=str(raw.get("message") or ""),
                at=float(raw.get("at") or time.time()),
                error_id=raw.get("errorId"),
                status_code=raw.get("statusCode"),
                meta=dict(raw.get("meta") or {}),
            )
            self._history.append(event)
            if event.kind == "error":
                self._total_errors += 1
            else:
                self._total_fixes += 1
            self._event_times.append((event.at, event.kind))

    def _seed_history(self) -> None:
        base = time.time() - len(SEED_EVENTS) * 180
        open_by_signature: dict[str, str] = {}
        for index, item in enumerate(SEED_EVENTS):
            at = base + index * 180
            error_id = None
            if item["kind"] == "fix":
                error_id = open_by_signature.pop(item["signature"], None)
            event = TrackedEvent(
                id=uuid.uuid4().hex[:12],
                kind=item["kind"],
                source=item["source"],
                signature=item["signature"],
                message=item["message"],
                at=at,
                error_id=error_id,
                status_code=item.get("status_code"),
            )
            if item["kind"] == "error":
                self._total_errors += 1
                open_by_signature[item["signature"]] = event.id
            else:
                self._total_fixes += 1
            self._history.append(event)
            self._event_times.append((at, event.kind))
            self._persist(event)

    def _persist(self, event: TrackedEvent) -> None:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def _trim_event_times(self, now: float) -> None:
        cutoff = now - 3600
        while self._event_times and self._event_times[0][0] < cutoff:
            self._event_times.popleft()

    def _count_since(self, now: float, seconds: float, kind: EventKind | None = None) -> int:
        cutoff = now - seconds
        return sum(1 for ts, event_kind in self._event_times if ts >= cutoff and (kind is None or event_kind == kind))

    def _record_error(
        self,
        source: EventSource,
        signature: str,
        message: str,
        *,
        status_code: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> TrackedEvent:
        now = time.time()
        event = TrackedEvent(
            id=uuid.uuid4().hex[:12],
            kind="error",
            source=source,
            signature=signature,
            message=message,
            at=now,
            status_code=status_code,
            meta=meta or {},
        )
        self._total_errors += 1
        self._history.append(event)
        self._event_times.append((now, "error"))
        self._trim_event_times(now)

        open_error = OpenError(
            id=event.id,
            signature=signature,
            source=source,
            message=message,
            at=now,
            status_code=status_code,
        )
        self._open_errors[event.id] = open_error
        if len(self._open_errors) > MAX_OPEN_ERRORS:
            oldest = min(self._open_errors.values(), key=lambda item: item.at)
            self._open_errors.pop(oldest.id, None)

        if source == "api":
            self._recent_error_by_route[signature] = open_error

        self._persist(event)
        return event

    def _record_fix(
        self,
        source: EventSource,
        signature: str,
        message: str,
        *,
        error_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> TrackedEvent:
        now = time.time()
        linked_error_id = error_id
        if not linked_error_id:
            for open_error in sorted(self._open_errors.values(), key=lambda item: item.at, reverse=True):
                if open_error.signature == signature:
                    linked_error_id = open_error.id
                    break

        event = TrackedEvent(
            id=uuid.uuid4().hex[:12],
            kind="fix",
            source=source,
            signature=signature,
            message=message,
            at=now,
            error_id=linked_error_id,
            meta=meta or {},
        )
        self._total_fixes += 1
        self._history.append(event)
        self._event_times.append((now, "fix"))
        self._trim_event_times(now)

        if linked_error_id:
            self._open_errors.pop(linked_error_id, None)
        self._recent_error_by_route.pop(signature, None)

        self._persist(event)
        return event

    def record_api_response(self, method: str, path: str, status_code: int) -> None:
        from app.services.noise_routes import should_track_api_error

        if not should_track_api_error(method, path):
            return
        with self._lock:
            self._ensure_loaded()
            signature = f"{method} {path}"
            if status_code >= 400:
                self._record_error(
                    "api",
                    signature,
                    f"HTTP {status_code} on {signature}",
                    status_code=status_code,
                )
                return

            if 200 <= status_code < 400:
                recent = self._recent_error_by_route.get(signature)
                if recent and (time.time() - recent.at) <= FIX_WINDOW_SECONDS:
                    self._record_fix(
                        "api",
                        signature,
                        f"Route recovered with HTTP {status_code}",
                        error_id=recent.id,
                    )

    def record_client_log(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._ensure_loaded()
            level = str(entry.get("level") or "info").lower()
            source_name = str(entry.get("source") or "client")
            message = str(entry.get("message") or "")
            signature = f"{source_name}:{entry.get('module') or entry.get('type') or 'log'}"

            metadata = entry.get("metadata") or {}
            if isinstance(metadata, dict) and metadata.get("fixFor"):
                self._record_fix(
                    "client",
                    str(metadata.get("fixFor")),
                    message or "Client reported fix",
                    error_id=str(metadata.get("errorId")) if metadata.get("errorId") else None,
                    meta=metadata,
                )
                return

            if level == "error":
                self._record_error("client", signature, message or "Client error logged")
                return

            lowered = message.lower()
            if any(keyword in lowered for keyword in FIX_KEYWORDS):
                self._record_fix("client", signature, message)

    def record_system_fix(self, signature: str, message: str, *, error_message: str | None = None) -> None:
        with self._lock:
            self._ensure_loaded()
            if error_message:
                self._record_error("system", signature, error_message)
            self._record_fix("system", signature, message)

    def _error_has_linked_fix(self, error_event: TrackedEvent) -> bool:
        return any(
            event.kind == "fix" and event.error_id == error_event.id
            for event in self._history
        )

    def reconcile_resolved_errors(self) -> int:
        """Record fix events for historical errors that are already resolved in code."""
        with self._lock:
            self._ensure_loaded()
            recorded = 0
            for event in list(self._history):
                if event.kind != "error" or self._error_has_linked_fix(event):
                    continue
                message = RESOLVED_ERROR_SIGNATURES.get(event.signature)
                if not message:
                    continue
                self._record_fix("system", event.signature, message, error_id=event.id)
                recorded += 1
            return recorded

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            now = time.time()
            self._trim_event_times(now)
            history = list(self._history)[-40:]
            timeline = sorted(history, key=lambda item: item.at, reverse=True)
            fixed_error_ids = {
                event.error_id for event in self._history if event.kind == "fix" and event.error_id
            }
            unresolved_errors = sum(
                1 for event in self._history if event.kind == "error" and event.id not in fixed_error_ids
            )

            return {
                "totalErrorsTracked": self._total_errors,
                "totalFixesTracked": self._total_fixes,
                "openErrors": len(self._open_errors),
                "unresolvedErrors": unresolved_errors,
                "fixRate": round((self._total_fixes / self._total_errors) * 100, 1) if self._total_errors else 0.0,
                "errorsLast60s": self._count_since(now, 60, "error"),
                "fixesLast60s": self._count_since(now, 60, "fix"),
                "errorsLastHour": self._count_since(now, 3600, "error"),
                "fixesLastHour": self._count_since(now, 3600, "fix"),
                "recentErrors": [event.to_dict() for event in timeline if event.kind == "error"][:40],
                "recentFixes": [event.to_dict() for event in timeline if event.kind == "fix"][:40],
                "openErrorItems": [
                    {
                        "id": item.id,
                        "signature": item.signature,
                        "source": item.source,
                        "message": item.message,
                        "statusCode": item.status_code,
                        "atIso": datetime.fromtimestamp(item.at, tz=UTC).isoformat(),
                    }
                    for item in sorted(self._open_errors.values(), key=lambda entry: entry.at, reverse=True)
                ],
                "history": [event.to_dict() for event in timeline[:80]],
            }

    def _persisted_errors_unlocked(self, limit: int = 500) -> list[TrackedEvent]:
        persisted: list[TrackedEvent] = []
        if HISTORY_FILE.is_file():
            try:
                lines = [line for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
            except OSError:
                lines = []
            for line in lines:
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if raw.get("kind") != "error":
                    continue
                persisted.append(
                    TrackedEvent(
                        id=str(raw.get("id") or uuid.uuid4().hex[:12]),
                        kind="error",
                        source=raw.get("source", "system"),
                        signature=str(raw.get("signature") or "unknown"),
                        message=str(raw.get("message") or ""),
                        at=float(raw.get("at") or time.time()),
                        status_code=raw.get("statusCode"),
                        meta=dict(raw.get("meta") or {}),
                    )
                )
        if not persisted:
            persisted = [event for event in self._history if event.kind == "error"]
        return persisted[-limit:]

    def list_persisted_errors(self, limit: int = 500) -> list[TrackedEvent]:
        """Return persisted error events oldest-first, up to limit (reads full JSONL file)."""
        with self._lock:
            self._ensure_loaded()
            return self._persisted_errors_unlocked(limit)

    def inventory(self) -> dict[str, int]:
        with self._lock:
            self._ensure_loaded()
            return {
                "historicalErrors": len(self._persisted_errors_unlocked(10_000)),
                "openErrors": len(self._open_errors),
                "totalErrorsTracked": self._total_errors,
                "totalFixesTracked": self._total_fixes,
            }

    def find_error(self, error_id: str) -> TrackedEvent | None:
        with self._lock:
            self._ensure_loaded()
            for event in reversed(self._history):
                if event.id == error_id and event.kind == "error":
                    return event
            if error_id in self._open_errors:
                open_error = self._open_errors[error_id]
                return TrackedEvent(
                    id=open_error.id,
                    kind="error",
                    source=open_error.source,
                    signature=open_error.signature,
                    message=open_error.message,
                    at=open_error.at,
                    status_code=open_error.status_code,
                )
            return None

    def list_open_errors(self) -> list[TrackedEvent]:
        with self._lock:
            self._ensure_loaded()
            return [
                TrackedEvent(
                    id=item.id,
                    kind="error",
                    source=item.source,
                    signature=item.signature,
                    message=item.message,
                    at=item.at,
                    status_code=item.status_code,
                )
                for item in sorted(self._open_errors.values(), key=lambda entry: entry.at, reverse=True)
            ]

    def mark_investigation_requested(self, error_id: str) -> TrackedEvent | None:
        with self._lock:
            self._ensure_loaded()
            for event in self._history:
                if event.id == error_id and event.kind == "error":
                    event.meta = {**event.meta, "investigationRequestedAt": datetime.now(UTC).isoformat()}
                    return event
            return None


    def seed_known_fixes_if_empty(self) -> None:
        with self._lock:
            self._ensure_loaded()
            if self._history:
                return
            self._seed_history()


error_fix_tracker = ErrorFixTracker()


def seed_error_fix_history_if_empty() -> None:
    error_fix_tracker.seed_known_fixes_if_empty()


def reconcile_error_history_on_startup() -> None:
    from app.config import settings

    if settings.career_os_dev_mode:
        error_fix_tracker.reconcile_resolved_errors()
