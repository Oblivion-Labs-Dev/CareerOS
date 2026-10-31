"""Hosted-production security: cross-site requests, rate-limit identity, and
internal-address blocking for user-supplied URLs and the automated browser."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app
from app.middleware.csrf import CrossSiteRequestGuardMiddleware
from app.middleware.rate_limit import MAX_TRACKED_CLIENTS, RateLimitMiddleware
from app.services.application_assistant import url_validation
from app.services.application_assistant.url_validation import (
    guard_browser_request,
    private_address_reason,
    refuse_private_http_request,
    validate_url,
)


def _guarded_app() -> FastAPI:
    test_app = FastAPI()
    test_app.add_middleware(
        CrossSiteRequestGuardMiddleware,
        allowed_origins=["https://careeros.example"],
        allowed_origin_regex=None,
    )

    @test_app.post("/act")
    def act():
        return {"ok": True}

    @test_app.get("/read")
    def read():
        return {"ok": True}

    return test_app


# --- CSRF -------------------------------------------------------------------

def test_a_post_from_another_site_is_refused():
    client = TestClient(_guarded_app())
    assert client.post("/act", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/act", headers={"Origin": "null"}).status_code == 403
    # Through the Next.js proxy Origin is stripped; Sec-Fetch-Site survives.
    assert client.post("/act", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/act", headers={"Sec-Fetch-Site": "same-site"}).status_code == 403


def test_same_origin_and_non_browser_posts_still_work():
    client = TestClient(_guarded_app())
    assert client.post("/act", headers={"Origin": "https://careeros.example"}).status_code == 200
    assert client.post("/act", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert client.post("/act").status_code == 200  # curl, the Next.js server
    assert client.get("/read", headers={"Origin": "https://evil.example"}).status_code == 200


def test_the_real_app_refuses_a_cross_site_post():
    """Wired into app.main ahead of every route, with or without a password."""
    client = TestClient(app)
    response = client.post(
        "/application-assistant/autopilot/stop", headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 403


# --- Rate limiting ----------------------------------------------------------

def _request(peer: str, xff: str | None = None):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_a_direct_caller_cannot_choose_its_bucket_with_x_forwarded_for(monkeypatch):
    monkeypatch.delenv("CAREER_OS_TRUSTED_PROXIES", raising=False)
    limiter = RateLimitMiddleware(FastAPI())
    assert limiter._get_client_ip(_request("203.0.113.9", "1.2.3.4")) == "203.0.113.9"


def test_behind_the_local_proxy_the_last_untrusted_hop_is_the_client(monkeypatch):
    monkeypatch.delenv("CAREER_OS_TRUSTED_PROXIES", raising=False)
    limiter = RateLimitMiddleware(FastAPI())
    # Client-written entries on the left are ignored.
    assert limiter._get_client_ip(_request("127.0.0.1", "6.6.6.6, 198.51.100.7")) == "198.51.100.7"
    assert limiter._get_client_ip(_request("127.0.0.1")) == "127.0.0.1"


def test_configured_proxies_are_skipped(monkeypatch):
    monkeypatch.setenv("CAREER_OS_TRUSTED_PROXIES", "10.0.0.0/8")
    limiter = RateLimitMiddleware(FastAPI())
    assert limiter._get_client_ip(_request("127.0.0.1", "198.51.100.7, 10.1.2.3")) == "198.51.100.7"


def _limited_app(rpm: int) -> tuple[FastAPI, list]:
    test_app = FastAPI()
    holder: list = []

    class Capturing(RateLimitMiddleware):
        def __init__(self, inner, **kw):
            super().__init__(inner, **kw)
            holder.append(self)

    test_app.add_middleware(Capturing, requests_per_minute=rpm)

    @test_app.get("/auth/me")
    def me():
        return {}

    @test_app.post("/auth/login")
    def login():
        return {}

    return test_app, holder


def test_login_has_its_own_bucket():
    test_app, _ = _limited_app(rpm=1000)
    client = TestClient(test_app)
    for _ in range(20):
        client.get("/auth/me")
    # /auth/me traffic shares the "auth" path segment but not the login budget.
    assert client.post("/auth/login").status_code == 200
    statuses = [client.post("/auth/login").status_code for _ in range(15)]
    assert statuses[-1] == 429


def test_the_window_table_is_bounded(monkeypatch):
    import app.middleware.rate_limit as rl

    monkeypatch.setattr(rl, "MAX_TRACKED_CLIENTS", 5)
    # TestClient's peer is not an IP; give every request its own identity.
    monkeypatch.setattr(rl.RateLimitMiddleware, "_get_client_ip",
                        lambda self, request: request.headers["x-forwarded-for"])
    test_app, holder = _limited_app(rpm=100)
    client = TestClient(test_app)
    for i in range(30):
        client.get("/auth/me", headers={"x-forwarded-for": f"198.51.100.{i}"})
    assert len(holder[0].windows) <= 5
    assert MAX_TRACKED_CLIENTS >= 1000


# --- Internal addresses -----------------------------------------------------

@pytest.mark.parametrize("host", ["169.254.169.254", "10.0.0.5", "192.168.1.1", "172.16.0.1",
                                  "100.64.0.1", "0.0.0.0", "[::ffff:10.0.0.1]", "[fd00::1]"])
def test_internal_addresses_are_refused_everywhere(host, monkeypatch):
    monkeypatch.delenv("CAREEROS_ENV", raising=False)
    assert private_address_reason(host, resolve=False)
    valid, reason = validate_url(f"http://{host}/latest/meta-data/")
    assert not valid and "Refusing" in reason


def test_loopback_is_refused_only_when_hosted(monkeypatch):
    monkeypatch.delenv("CAREEROS_ENV", raising=False)
    assert validate_url("http://127.0.0.1:4000/x")[0]  # local fixture servers
    monkeypatch.setenv("CAREEROS_ENV", "production")
    assert not validate_url("http://127.0.0.1:4000/x")[0]
    assert not validate_url("http://localhost:4000/x")[0]


def test_a_public_name_resolving_inward_is_refused(monkeypatch):
    monkeypatch.setattr(url_validation.socket, "getaddrinfo",
                        lambda host, port: [(2, 1, 6, "", ("10.1.2.3", 0))])
    assert not validate_url("https://jobs.innocent.example/apply")[0]


def test_public_and_unresolvable_names_pass(monkeypatch):
    monkeypatch.setattr(url_validation.socket, "getaddrinfo",
                        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))])
    assert validate_url("https://boards.greenhouse.io/acme/jobs/1")[0]

    def no_dns(host, port):
        raise OSError("no network")

    monkeypatch.setattr(url_validation.socket, "getaddrinfo", no_dns)
    assert validate_url("https://boards.greenhouse.io/acme/jobs/1")[0]


class _Route:
    def __init__(self, url: str, navigation: bool):
        self.request = SimpleNamespace(url=url, is_navigation_request=lambda: navigation)
        self.outcome = None

    async def abort(self):
        self.outcome = "aborted"

    async def continue_(self):
        self.outcome = "continued"


def _fake_dns(monkeypatch, table):
    monkeypatch.setattr(url_validation, "_host_reason_cache", {})
    lookups = []

    def getaddrinfo(host, port):
        lookups.append(host)
        return [(2, 1, 6, "", (table[host], 0))]

    monkeypatch.setattr(url_validation.socket, "getaddrinfo", getaddrinfo)
    return lookups


def test_the_browser_guard_blocks_internal_targets(monkeypatch):
    _fake_dns(monkeypatch, {"redirect-to-inside.example": "10.9.9.9", "metadata.internal.example": "169.254.169.254",
                            "cdn.example": "93.184.216.34"})
    cases = [
        (_Route("http://169.254.169.254/latest/", navigation=False), "aborted"),
        (_Route("https://redirect-to-inside.example/", navigation=True), "aborted"),
        (_Route("mailto:jobs@acme.example", navigation=True), "aborted"),
        # An employer page's <img>/fetch() to a name that resolves inward
        # (Codex review): a subresource probe of the network all the same.
        (_Route("http://metadata.internal.example/latest/", navigation=False), "aborted"),
        (_Route("https://cdn.example/app.js", navigation=False), "continued"),
    ]
    for route, expected in cases:
        asyncio.run(guard_browser_request(route))
        assert route.outcome == expected, route.request.url


def test_the_browser_guard_resolves_each_host_once_per_minute(monkeypatch):
    lookups = _fake_dns(monkeypatch, {"cdn.example": "93.184.216.34"})
    for _ in range(20):
        asyncio.run(guard_browser_request(_Route("https://cdn.example/app.js", navigation=False)))
    assert lookups == ["cdn.example"]


def test_the_careers_url_fetch_refuses_redirects_inward(monkeypatch):
    import httpx

    monkeypatch.setattr(url_validation.socket, "getaddrinfo",
                        lambda host, port: [(2, 1, 6, "", ("169.254.169.254", 0))])
    with pytest.raises(PermissionError):
        asyncio.run(refuse_private_http_request(httpx.Request("GET", "http://metadata.example/")))


# --- Error body -------------------------------------------------------------

def test_hosted_500_does_not_echo_the_exception(monkeypatch):
    from app.main import global_exception_handler

    request = SimpleNamespace(method="GET", url=SimpleNamespace(path="/x"))
    monkeypatch.setenv("CAREEROS_ENV", "production")
    body = asyncio.run(global_exception_handler(request, RuntimeError("/secret/path"))).body
    assert b"/secret/path" not in body
