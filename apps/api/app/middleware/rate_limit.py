"""Production sliding-window rate limiting middleware for CareerOS API.

Protects against:
- Brute-force attacks on /auth/login
- Expensive LLM/PyMuPDF resource exhaustion on /api/parse-resume
- Scraping and unauthenticated request floods
"""

from __future__ import annotations

import time
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 120, burst_multiplier: float = 1.5):
        super().__init__(app)
        self.rpm = requests_per_minute
        self.burst = int(requests_per_minute * burst_multiplier)
        # Store timestamp logs per client IP: {client_ip: [timestamp1, timestamp2, ...]}
        self.windows: dict[str, list[float]] = defaultdict(list)
        # Specific strict limits for sensitive endpoints: (path_prefix, max_per_minute)
        self.strict_limits = [
            ("/auth/login", 15),
            ("/api/parse-resume", 20),
            ("/api/onboarding/answers", 30),
        ]

    def _get_client_ip(self, request: Request) -> str:
        # Check standard reverse proxy headers
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        if request.client and request.client.host:
            return request.client.host
        return "127.0.0.1"

    async def dispatch(self, request: Request, call_next) -> Response:
        # Ignore CORS preflight and lightweight health probes
        if request.method == "OPTIONS" or request.url.path in ("/health", "/favicon.ico"):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        now = time.time()
        minute_ago = now - 60.0

        # Determine limit for current path
        allowed_limit = self.rpm
        for prefix, limit in self.strict_limits:
            if request.url.path.startswith(prefix):
                allowed_limit = limit
                break

        key = f"{client_ip}:{request.url.path.split('/')[1] if len(request.url.path.split('/')) > 1 else 'root'}"

        # Clean old timestamps outside sliding 60-second window
        timestamps = [t for t in self.windows[key] if t > minute_ago]
        self.windows[key] = timestamps

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

        self.windows[key].append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(allowed_limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, allowed_limit - len(timestamps) - 1))
        return response
