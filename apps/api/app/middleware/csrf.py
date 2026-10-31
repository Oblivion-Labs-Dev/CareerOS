"""Cross-site request forgery guard for every state-changing request.

The session cookie is SameSite=Lax, but that alone leaves two holes: the gate
is off until CAREER_OS_ADMIN_PASSWORD is set, so any web page the owner visits
could POST to the local API (no cookie needed), and the Next.js proxy strips
Origin before forwarding. Browsers mark every request with Sec-Fetch-Site and,
for cross-origin POSTs, Origin, and a page cannot forge either. So a
state-changing request is refused when the browser says it came from another
site. Requests without those headers (curl, the Next.js server itself, other
services) are not browser-driven and are left to the auth gate.
"""

from __future__ import annotations

import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CrossSiteRequestGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_origins: list[str], allowed_origin_regex: str | None = None):
        super().__init__(app)
        self.allowed_origins = {o.rstrip("/") for o in allowed_origins}
        self.allowed_origin_re = re.compile(allowed_origin_regex) if allowed_origin_regex else None

    def _origin_allowed(self, origin: str) -> bool:
        origin = origin.rstrip("/")
        if origin in self.allowed_origins:
            return True
        return bool(self.allowed_origin_re and self.allowed_origin_re.fullmatch(origin))

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None:
                refused = not self._origin_allowed(origin)
            else:
                # Same-origin (through the proxy, which drops Origin) and
                # user-initiated ("none") are fine; another site is not.
                refused = request.headers.get("sec-fetch-site", "").lower() in ("cross-site", "same-site")
            if refused:
                return JSONResponse(status_code=403, content={"detail": "Cross-site request refused"})
        return await call_next(request)
