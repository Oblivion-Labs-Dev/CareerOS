"""Production sliding-window rate limiting middleware for CareerOS API.

Protects against:
- Brute-force attacks on /auth/login
- Expensive LLM/PyMuPDF resource exhaustion on /api/parse-resume
- Scraping and unauthenticated request floods
"""

from __future__ import annotations

import ipaddress
import os
import time
from collections import deque
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

#: Most client windows held at once. Past this the idle ones are dropped, so a
#: flood of distinct addresses cannot grow the table without bound.
MAX_TRACKED_CLIENTS = 10_000


def _trusted_proxies() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Peers whose X-Forwarded-For is believed: the Next.js proxy on this
    machine by default, plus CAREER_OS_TRUSTED_PROXIES (comma-separated IPs or
    CIDRs) for anything in front of it."""
    raw = os.environ.get("CAREER_OS_TRUSTED_PROXIES", "")
    nets = [ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("::1/128")]
    for item in raw.split(","):
        item = item.strip()
        if item:
            try:
                nets.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                pass
    return nets


def _is_trusted(address: str, nets) -> bool:
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        return False
    return any(ip in net for net in nets)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 120, burst_multiplier: float = 1.5):
        super().__init__(app)
        self.rpm = requests_per_minute
        self.burst = int(requests_per_minute * burst_multiplier)
        # Request timestamps per (client, bucket) within the last minute.
        self.windows: dict[str, deque[float]] = {}
        # Specific strict limits for sensitive endpoints: (path_prefix, max_per_minute)
        self.strict_limits = [
            ("/auth/login", 15),
            ("/api/parse-resume", 20),
            ("/api/onboarding/answers", 30),
        ]
        self.trusted_proxies = _trusted_proxies()

    def _get_client_ip(self, request: Request) -> str:
        """The socket peer, unless it is a trusted proxy: then the right-most
        X-Forwarded-For entry that is not itself a trusted proxy. Entries to
        the left of that were written by the client and are never believed —
        trusting the left-most one let any caller pick its own bucket."""
        peer = request.client.host if request.client and request.client.host else "127.0.0.1"
        if not _is_trusted(peer, self.trusted_proxies):
            return peer
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        for hop in reversed(hops):
            if not _is_trusted(hop, self.trusted_proxies):
                return hop
        return hops[0] if hops else peer

    def _prune(self, minute_ago: float) -> None:
        for key in [k for k, ts in self.windows.items() if not ts or ts[-1] <= minute_ago]:
            del self.windows[key]
        while len(self.windows) >= MAX_TRACKED_CLIENTS:
            del self.windows[next(iter(self.windows))]

    async def dispatch(self, request: Request, call_next) -> Response:
        # Ignore CORS preflight and lightweight health probes
        if request.method == "OPTIONS" or request.url.path in ("/health", "/favicon.ico"):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        now = time.time()
        minute_ago = now - 60.0

        # A strict endpoint gets a bucket of its own, so ordinary traffic under
        # the same first path segment (/auth/me) cannot use up login attempts.
        allowed_limit = self.rpm
        bucket = request.url.path.split("/")[1] if len(request.url.path.split("/")) > 1 else "root"
        for prefix, limit in self.strict_limits:
            if request.url.path.startswith(prefix):
                allowed_limit = limit
                bucket = prefix
                break

        key = f"{client_ip}:{bucket}"
        timestamps = self.windows.get(key)
        if timestamps is None:
            if len(self.windows) >= MAX_TRACKED_CLIENTS:
                self._prune(minute_ago)
            timestamps = self.windows[key] = deque()
        # Clean old timestamps outside sliding 60-second window
        while timestamps and timestamps[0] <= minute_ago:
            timestamps.popleft()

        if len(timestamps) >= allowed_limit:
            oldest = timestamps[0]
            retry_after = int(max(1.0, 60.0 - (now - oldest)))
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please slow down.",
                    "retryAfter": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        timestamps.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(allowed_limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, allowed_limit - len(timestamps)))
        return response
