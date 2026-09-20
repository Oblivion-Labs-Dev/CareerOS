from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.services.auth import SESSION_COOKIE_NAME, is_auth_configured, verify_session_token

# Paths reachable without a session — the login flow itself, health checks used
# by the dev tooling, and static assets that carry no data.
_ALLOWLIST_PREFIXES = ("/auth/", "/health", "/favicon.ico", "/static/")

# KNOWN LIMITATION: only /application-assistant/* and /diagnostic/* are
# enforced. Everything else — profile, job discovery, settings, email,
# analytics, resume intelligence — answers without a session, so the "login" is
# really the Next.js page-level redirect in middleware.ts.
#
# The reason recorded here previously is now out of date, and the correction
# matters because it changes how much work the fix is. It said most of the app
# called the API cross-origin so the cookie could not reach it. That has since
# been fixed centrally: lib/api.ts's getClientApiBaseUrl() returns
# "/api/backend" in the browser, and postJson/fetchJson both send
# `credentials: "include"`, so the ordinary dashboard paths already travel
# same-origin through the proxy and do carry the session.
#
# What is actually left, verified by grep rather than assumed, is eight browser
# components that still build a fetch URL from NEXT_PUBLIC_API_URL:
#
#     components/apply-pilot-installer.tsx
#     components/benchmark/benchmark-dashboard.tsx      (defaults to port 8000)
#     components/benchmark/dummy-job-testing-app.tsx    (defaults to port 8000)
#     components/benchmark/matcher-benchmark.tsx
#     components/dashboard/autopilot-activity-card.tsx
#     components/landing-firefox-install.tsx
#     components/ui/model-benchmark-selector.tsx
#     app/dev/repair/page.tsx
#
# (app/api/*/route.ts also reference the origin, but those are the server-side
# proxy handlers and are supposed to.)
#
# So widening _ENFORCED_PREFIXES is now a small job, not a large one: move those
# eight onto getClientApiBaseUrl(), then flip this to deny-by-default with an
# allowlist of /auth/, /health, /favicon.ico and /static/. Do it in that order —
# reversing it 401s those panels — and add one test per router asserting 401
# without a cookie, so the limitation cannot quietly come back.
# Deny by default. Everything not on the allowlist above needs a session.
#
# This used to be an allowlist of two prefixes, leaving profile, job discovery,
# settings, email, analytics and resume intelligence readable by anyone who
# could reach the port — the "login" was really just the Next.js page redirect.
# The blocker recorded for that was stale (see above); the eight components that
# genuinely still bypassed the proxy have since been moved onto
# getClientApiBaseUrl(), so the dashboard now travels same-origin and carries
# the cookie.
#
# Kept as an explicit empty tuple rather than deleted, because the *shape* of
# the decision matters: adding a prefix here would silently re-open a hole, and
# a reader should see that the enforcement is deliberate and total.
_ENFORCED_PREFIXES: tuple[str, ...] = ()


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

        # An empty _ENFORCED_PREFIXES now means "enforce everything", which is
        # the opposite of what `startswith(())` returns — it is False for every
        # path, so the original early-return would have waved the whole API
        # through the moment the tuple was emptied. Only narrow enforcement when
        # the tuple is non-empty.
        if _ENFORCED_PREFIXES and not request.url.path.startswith(_ENFORCED_PREFIXES):
            return await call_next(request)

        session = verify_session_token(request.cookies.get(SESSION_COOKIE_NAME))
        if not session:
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

        return await call_next(request)
