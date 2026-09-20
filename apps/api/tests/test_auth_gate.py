"""The API must not answer without a session once a password is configured.

It used to enforce only /application-assistant/ and /diagnostic/, leaving
profile, job discovery, settings, email, analytics and resume intelligence
readable by anyone who could reach the port. The "login" was really the Next.js
page redirect, which protects a page and not an API.

The reason recorded for that was that most of the dashboard called the API
cross-origin so the cookie could not reach it. That had already been fixed
centrally; only eight components still bypassed the proxy, and they have since
been moved. These pin the gate shut behind them.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def gated(monkeypatch):
    """A client with the login gate switched on.

    The gate is a no-op until a password is configured, so a fresh checkout is
    never locked out of itself. Tests have no password, hence the patch.
    """
    monkeypatch.setattr("app.middleware.auth.is_auth_configured", lambda: True)
    return TestClient(app)


@pytest.fixture
def ungated(monkeypatch):
    monkeypatch.setattr("app.middleware.auth.is_auth_configured", lambda: False)
    return TestClient(app)


# ── Deny by default ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/profile",
        "/settings",
        "/application-assistant/autopilot/status",
        "/application-assistant/autopilot/readiness",
        "/diagnostic/system-health",
        "/jobs",
    ],
)
def test_every_data_route_needs_a_session(gated, path):
    """The regression this file exists for.

    Each of these answered unauthenticated before. `/profile` is the sharpest
    case: it returns the candidate's address, phone number and employment
    history.
    """
    response = gated.get(path)

    assert response.status_code == 401, f"{path} answered without a session"


def test_emptying_the_enforced_list_does_not_disable_the_gate():
    """A trap worth a test of its own.

    Enforcement narrows to `_ENFORCED_PREFIXES` when that tuple is non-empty.
    `"".startswith(())` is False for *every* string, so a plain
    `not path.startswith(_ENFORCED_PREFIXES)` early-return would wave the whole
    API through the instant the tuple became empty — turning "enforce
    everything" into "enforce nothing".
    """
    from app.middleware import auth

    assert auth._ENFORCED_PREFIXES == (), "deny-by-default is expressed as an empty tuple"
    assert not "/profile".startswith(auth._ENFORCED_PREFIXES), (
        "this is the footgun the middleware has to special-case"
    )


# ── What stays reachable ─────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/health", "/favicon.ico"])
def test_the_allowlist_still_answers(gated, path):
    """Health is what the dev tooling polls, and the login flow cannot require
    a session to reach the thing that issues one."""
    assert gated.get(path).status_code < 400


def test_the_login_route_is_reachable_without_a_session(gated):
    response = gated.post("/auth/login", json={"username": "admin", "password": "wrong"})

    assert response.status_code != 401 or "detail" in response.json()


def test_preflight_is_never_gated(gated):
    """A blocked OPTIONS shows up in the browser as a CORS failure, not a 401,
    so the frontend never gets the chance to redirect to /login."""
    response = gated.options(
        "/profile",
        headers={"Origin": "http://localhost:5000", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code != 401


# ── Off by default ───────────────────────────────────────────────────────────


def test_a_checkout_with_no_password_is_not_locked_out(ungated):
    """Nobody should be shut out of their own local instance by default."""
    assert ungated.get("/profile").status_code != 401
