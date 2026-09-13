from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.services.auth import SESSION_COOKIE_NAME, is_auth_configured, verify_session_token

# Paths reachable without a session — the login flow itself, health checks used
# by the dev tooling, and static assets that carry no data.
_ALLOWLIST_PREFIXES = ("/auth/", "/health", "/favicon.ico", "/static/")

# KNOWN LIMITATION, deliberate for now: only /application-assistant/* is enforced
# here. That's the one part of the API the web app calls through the same-origin
# `/api/backend` proxy (see app/api/backend/[...path]/route.ts), which is what
# carries the session cookie correctly. Most of the rest of the app (profile,
# job discovery, settings, email, analytics, ~25 files) calls the API directly
# from the browser at a different port via lib/api.ts's getClientApiBaseUrl(),
# which is a different origin — the cookie set at login doesn't reach those
# requests without `credentials: "include"` on every one of those call sites
# (not yet done; real fix is migrating them to the proxy pattern, matching
# application-assistant-api.ts). Enforcing broadly right now 401s all of that
# and breaks most of the dashboard. Until that migration happens, the Next.js
# middleware's page-level redirect (middleware.ts) is the actual gate a casual
# visitor hits; this only additionally locks down the live-submission surface.
_ENFORCED_PREFIXES = ("/application-assistant/", "/diagnostic/")


class AuthGateMiddleware(BaseHTTPMiddleware):
    """Enforces the single-user login gate (see app/services/auth.py) once
    CAREER_OS_ADMIN_PASSWORD is set. A no-op until then, so a fresh checkout with
    no .env behaves exactly as before — nobody gets locked out of their own local
    instance by default. See _ENFORCED_PREFIXES above for current scope."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS" or not is_auth_configured():
            return await call_next(request)

        if request.url.path.startswith(_ALLOWLIST_PREFIXES):
            return await call_next(request)

        if not request.url.path.startswith(_ENFORCED_PREFIXES):
            return await call_next(request)

        session = verify_session_token(request.cookies.get(SESSION_COOKIE_NAME))
        if not session:
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

        return await call_next(request)
