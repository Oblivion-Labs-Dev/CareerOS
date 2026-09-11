"""Counters for the Gemini layer, and the circuit state shared between processes.

Two things live here rather than one, because they have different lifetimes and
different readers.

**Telemetry** is in-memory and per-process, like `LLMCallMetrics` beside it. It
answers "what has Gemini done since the backend started" for the diagnostics
page, and it is cheap enough to update on every call.

**Circuit state** has to outlive one process and be visible from all of them.
CareerOS runs the API in one process and the Playwright executor in another, and
if the API has just learned that Gemini is returning 404 for a misconfigured
model, the executor must not spend the next five minutes discovering the same
thing. So the breaker's state is mirrored to a small JSON file that every
process re-reads before it decides whether a call is allowed. Writes are atomic
(temp file plus replace) because two processes can write it at once.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

STATE_DIR = Path(__file__).resolve().parents[3] / "data" / "gemini"
CIRCUIT_FILE = STATE_DIR / "circuit.json"

#: How stale a read of the shared circuit file may be before a process re-reads
#: it. Short enough that a circuit opened elsewhere is respected almost at once,
#: long enough that a burst of calls does not stat the file every time.
CIRCUIT_REFRESH_SECONDS = 2.0

#: Latency samples kept for the percentiles. A few hundred is plenty to make p95
#: meaningful and small enough that the list never matters for memory.
LATENCY_WINDOW = 500

#: Recent failures kept for the diagnostics page, so a reader can see *what*
#: went wrong rather than only how often.
EVENT_WINDOW = 40


class GeminiTelemetry:
    """Process-wide counters. Thread-safe; reset on restart."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.started_at = time.time()
            self.requests = 0
            self.successes = 0
            self.failures = 0
            self.cache_hits = 0
            self.dedupe_hits = 0
            self.retries = 0
            self.rate_limited = 0
            self.server_errors = 0
            self.config_errors = 0
            self.permanent_errors = 0
            self.malformed = 0
            self.timeouts = 0
            self.circuit_rejections = 0
            self.fallbacks = 0
            self.review_stagings = 0
            self.prompt_tokens = 0
            self.completion_tokens = 0
            self._by_task: dict[str, dict[str, int]] = {}
            self._latency: deque[float] = deque(maxlen=LATENCY_WINDOW)
            self._events: deque[dict[str, Any]] = deque(maxlen=EVENT_WINDOW)

    # ── recording ────────────────────────────────────────────────────────────

    def _task_bucket(self, task: str) -> dict[str, int]:
        return self._by_task.setdefault(
            task,
            {"requests": 0, "success": 0, "failure": 0, "cacheHits": 0, "fallbacks": 0},
        )

    def record_request(self, task: str) -> None:
        with self._lock:
            self.requests += 1
            self._task_bucket(task)["requests"] += 1

    def record_cache_hit(self, task: str, *, deduped: bool = False) -> None:
        with self._lock:
            if deduped:
                self.dedupe_hits += 1
            else:
                self.cache_hits += 1
            self._task_bucket(task)["cacheHits"] += 1

    def record_success(
        self, task: str, latency_ms: float, *, prompt_tokens: int = 0, completion_tokens: int = 0
    ) -> None:
        with self._lock:
            self.successes += 1
            self._task_bucket(task)["success"] += 1
            self._latency.append(latency_ms)
            self.prompt_tokens += max(0, prompt_tokens)
            self.completion_tokens += max(0, completion_tokens)

    def record_failure(self, task: str, outcome: str, detail: str = "") -> None:
        with self._lock:
            self.failures += 1
            self._task_bucket(task)["failure"] += 1
            counter = {
                "rate_limited": "rate_limited",
                "transient": "server_errors",
                "config_error": "config_errors",
                "permanent": "permanent_errors",
                "malformed": "malformed",
                "timeout": "timeouts",
                "circuit_open": "circuit_rejections",
            }.get(outcome)
            if counter:
                setattr(self, counter, getattr(self, counter) + 1)
            self._events.appendleft({
                "at": time.strftime("%H:%M:%S"),
                "task": task,
                "outcome": outcome,
                "detail": detail[:200],
            })

    def record_retry(self) -> None:
        with self._lock:
            self.retries += 1

    def record_fallback(self, task: str) -> None:
        """A caller went to its deterministic path because Gemini did not answer."""
        with self._lock:
            self.fallbacks += 1
            self._task_bucket(task)["fallbacks"] += 1

    def record_review_staging(self) -> None:
        """An application went to REVIEW specifically because Gemini was unavailable."""
        with self._lock:
            self.review_stagings += 1

    # ── reading ──────────────────────────────────────────────────────────────

    @staticmethod
    def _percentile(samples: list[float], fraction: float) -> float | None:
        if not samples:
            return None
        ordered = sorted(samples)
        index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
        return round(ordered[index], 1)

    def to_dict(self, config: Any | None = None) -> dict[str, Any]:
        with self._lock:
            samples = list(self._latency)
            attempted = self.successes + self.failures
            served = self.successes + self.cache_hits + self.dedupe_hits
            lookups = served + self.failures
            price_in = getattr(config, "price_in_per_mtok", 0.0) if config else 0.0
            price_out = getattr(config, "price_out_per_mtok", 0.0) if config else 0.0
            cost = (
                self.prompt_tokens / 1_000_000 * price_in
                + self.completion_tokens / 1_000_000 * price_out
            )
            return {
                "requests": self.requests,
                "apiCalls": attempted,
                "successes": self.successes,
                "failures": self.failures,
                "successRate": round(self.successes / attempted, 3) if attempted else None,
                "cacheHits": self.cache_hits,
                "dedupeHits": self.dedupe_hits,
                "cacheHitRate": round((self.cache_hits + self.dedupe_hits) / lookups, 3) if lookups else None,
                "retries": self.retries,
                "rateLimited429": self.rate_limited,
                "serverErrors503": self.server_errors,
                "configErrors404": self.config_errors,
                "permanentErrors": self.permanent_errors,
                "malformedResponses": self.malformed,
                "timeouts": self.timeouts,
                "circuitRejections": self.circuit_rejections,
                "fallbacks": self.fallbacks,
                "applicationsStagedForReview": self.review_stagings,
                "byTask": {task: dict(counts) for task, counts in self._by_task.items()},
                "latencyMs": {
                    "average": round(sum(samples) / len(samples), 1) if samples else None,
                    "p50": self._percentile(samples, 0.50),
                    "p95": self._percentile(samples, 0.95),
                    "samples": len(samples),
                },
                "tokens": {
                    "prompt": self.prompt_tokens,
                    "completion": self.completion_tokens,
                    "total": self.prompt_tokens + self.completion_tokens,
                },
                # The free tier bills nothing. This says what the same traffic
                # would cost at published paid rates, which is the number that
                # matters when deciding whether to lean on Gemini harder.
                "estimatedCostUsd": round(cost, 4),
                "estimatedCostNote": "Priced at paid-tier rates; a free-tier key is billed nothing.",
                "recentFailures": list(self._events)[:10],
                "uptimeSeconds": round(time.time() - self.started_at, 1),
            }


telemetry = GeminiTelemetry()


# ── shared circuit state ─────────────────────────────────────────────────────

def read_circuit() -> dict[str, Any]:
    """The circuit as last written by any CareerOS process. {} when never set."""
    try:
        return json.loads(CIRCUIT_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a missing or half-written file is just "no state"
        return {}


def write_circuit(state: dict[str, Any]) -> None:
    """Publish the circuit for other processes. Never raises."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        # Unique temp name: two processes replacing the same temp file would
        # have one of them deleting the other's work mid-write.
        temp = CIRCUIT_FILE.with_suffix(f".{os.getpid()}.tmp")
        temp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        os.replace(temp, CIRCUIT_FILE)
    except Exception:  # noqa: BLE001 - telemetry must never break a call
        pass
