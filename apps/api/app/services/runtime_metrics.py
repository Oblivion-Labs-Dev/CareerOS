from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.error_fix_tracker import error_fix_tracker

MAX_LATENCY_SAMPLES = 500
MAX_RECENT_REQUESTS = 30
TPS_WINDOW_SECONDS = 60


@dataclass
class RequestRecord:
    method: str
    path: str
    status_code: int
    duration_ms: float
    at: float


@dataclass
class RuntimeMetricsStore:
    started_at: float = field(default_factory=time.time)
    total_requests: int = 0
    total_errors: int = 0
    client_errors: int = 0
    server_errors: int = 0
    latency_ms: deque[float] = field(default_factory=lambda: deque(maxlen=MAX_LATENCY_SAMPLES))
    request_times: deque[float] = field(default_factory=deque)
    route_counts: dict[str, int] = field(default_factory=dict)
    method_counts: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    recent_requests: deque[RequestRecord] = field(default_factory=lambda: deque(maxlen=MAX_RECENT_REQUESTS))
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _trim_request_times(self, now: float) -> None:
        cutoff = now - TPS_WINDOW_SECONDS
        while self.request_times and self.request_times[0] < cutoff:
            self.request_times.popleft()

    def record(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        now = time.time()
        route_key = f"{method} {path}"
        status_bucket = str(status_code)

        with self._lock:
            self.total_requests += 1
            self.latency_ms.append(duration_ms)
            self.request_times.append(now)
            self._trim_request_times(now)

            self.route_counts[route_key] = self.route_counts.get(route_key, 0) + 1
            self.method_counts[method] = self.method_counts.get(method, 0) + 1
            self.status_counts[status_bucket] = self.status_counts.get(status_bucket, 0) + 1

            if status_code >= 400:
                self.total_errors += 1
            if 400 <= status_code < 500:
                self.client_errors += 1
            if status_code >= 500:
                self.server_errors += 1

            self.recent_requests.appendleft(
                RequestRecord(
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    at=now,
                )
            )

    def _percentile(self, values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, int(round((pct / 100) * (len(ordered) - 1)))))
        return ordered[index]

    def _count_since(self, now: float, seconds: float) -> int:
        cutoff = now - seconds
        return sum(1 for ts in self.request_times if ts >= cutoff)

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            self._trim_request_times(now)
            latencies = list(self.latency_ms)
            requests_last_minute = len(self.request_times)
            requests_last_10s = self._count_since(now, 10)
            top_routes = sorted(self.route_counts.items(), key=lambda item: item[1], reverse=True)[:8]

            recent = [
                {
                    "method": item.method,
                    "path": item.path,
                    "status": item.status_code,
                    "durationMs": round(item.duration_ms, 1),
                    "at": datetime.fromtimestamp(item.at, tz=UTC).isoformat(),
                }
                for item in list(self.recent_requests)[:12]
            ]

            return {
                "uptimeSeconds": round(now - self.started_at, 1),
                "totalRequests": self.total_requests,
                "totalErrors": self.total_errors,
                "clientErrors": self.client_errors,
                "serverErrors": self.server_errors,
                "latencyMs": {
                    "avg": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
                    "p50": round(self._percentile(latencies, 50), 1),
                    "p95": round(self._percentile(latencies, 95), 1),
                    "max": round(max(latencies), 1) if latencies else 0.0,
                },
                "tps": {
                    "last10s": round(requests_last_10s / 10, 2),
                    "last60s": round(requests_last_minute / TPS_WINDOW_SECONDS, 2),
                },
                "requestsLast60s": requests_last_minute,
                "methods": dict(sorted(self.method_counts.items(), key=lambda item: item[1], reverse=True)),
                "statusCodes": dict(sorted(self.status_counts.items(), key=lambda item: item[0])),
                "topRoutes": [{"route": route, "count": count} for route, count in top_routes],
                "recentRequests": recent,
                "updatedAt": datetime.now(UTC).isoformat(),
            }


metrics_store = RuntimeMetricsStore()


def should_skip_metrics(path: str) -> bool:
    return path in {"/metrics", "/", "/favicon.ico", "/robots.txt"}


def metrics_snapshot_with_logs(client_log_errors: int = 0) -> dict[str, Any]:
    payload = metrics_store.snapshot()
    payload["clientLogErrors"] = client_log_errors
    payload["errorFix"] = error_fix_tracker.snapshot()
    return payload
