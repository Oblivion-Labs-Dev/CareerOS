"""fetch_with_retry must retry what is worth retrying, and nothing else."""

from __future__ import annotations

import httpx
import pytest

from app.services.job_discover.scraper_service import build_verified_ssl_context, fetch_with_retry


class _Recorder:
    """Minimal stand-in for httpx.AsyncClient that scripts a sequence of outcomes."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def get(self, url, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else self.outcomes
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome, request=httpx.Request("GET", url))


@pytest.mark.anyio
async def test_success_on_first_attempt_does_not_retry():
    client = _Recorder([200])
    resp = await fetch_with_retry(client, "https://example.test/jobs")
    assert resp.status_code == 200
    assert client.calls == 1


@pytest.mark.anyio
async def test_404_is_not_retried():
    """A bad board slug will still be bad on the third attempt."""
    client = _Recorder([404, 404, 404])
    resp = await fetch_with_retry(client, "https://example.test/jobs")
    assert resp.status_code == 404
    assert client.calls == 1


@pytest.mark.anyio
async def test_500_is_retried_then_succeeds():
    client = _Recorder([500, 200])
    resp = await fetch_with_retry(client, "https://example.test/jobs")
    assert resp.status_code == 200
    assert client.calls == 2


@pytest.mark.anyio
async def test_429_is_retried():
    client = _Recorder([429, 200])
    resp = await fetch_with_retry(client, "https://example.test/jobs")
    assert resp.status_code == 200
    assert client.calls == 2


@pytest.mark.anyio
async def test_retries_are_capped():
    client = _Recorder([500, 500, 500])
    resp = await fetch_with_retry(client, "https://example.test/jobs")
    assert resp.status_code == 500
    assert client.calls == 3


@pytest.mark.anyio
async def test_timeout_exhausted_returns_none():
    """Callers already treat a falsy response as 'no jobs from this board'."""
    client = _Recorder(
        [httpx.ConnectTimeout("t"), httpx.ConnectTimeout("t"), httpx.ConnectTimeout("t")]
    )
    assert await fetch_with_retry(client, "https://example.test/jobs") is None
    assert client.calls == 3


@pytest.mark.anyio
async def test_transport_error_then_success():
    client = _Recorder([httpx.ConnectError("boom"), 200])
    resp = await fetch_with_retry(client, "https://example.test/jobs")
    assert resp.status_code == 200
    assert client.calls == 2


def test_tls_context_verifies_by_default():
    """The scrapers must not ship with verification disabled again."""
    import ssl

    ctx = build_verified_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
