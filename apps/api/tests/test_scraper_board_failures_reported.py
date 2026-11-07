"""A broken ATS board must show up as a source error, not as "no jobs".

The Greenhouse, Lever, Ashby and Workable scrapers used to wrap their whole
body in ``except Exception: return []``. A board that answered 200 with a body
the parser could not read (an HTML error page, a changed schema) was then
indistinguishable from a company with no matching roles: nothing reached
``LAST_SOURCE_REPORT["errors"]`` and the employer silently dropped out of the
run. ``scrape_jobs`` already records per-source exceptions, so the scrapers
just have to let them through.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.job_discover import scraper_service

BOARD_HOSTS = {
    "greenhouse": "boards-api.greenhouse.io",
    "lever": "api.lever.co",
    "ashby": "api.ashbyhq.com",
    "workable": "apply.workable.com",
}


@pytest.fixture(autouse=True)
def _no_backoff_wait(monkeypatch):
    real_sleep = scraper_service.asyncio.sleep

    async def no_wait(_delay, *args, **kwargs):
        await real_sleep(0)

    monkeypatch.setattr(scraper_service.asyncio, "sleep", no_wait)


@pytest.mark.parametrize("platform", sorted(BOARD_HOSTS))
def test_unparseable_board_is_reported_as_source_error(monkeypatch, platform):
    broken_host = BOARD_HOSTS[platform]

    def handler(request: httpx.Request) -> httpx.Response:
        # The board under test answers 200 with a body that is not JSON;
        # every other source sees a dead endpoint and contributes nothing.
        if request.url.host == broken_host:
            return httpx.Response(200, text="<html>Service temporarily unavailable</html>")
        return httpx.Response(404, text="")

    def mock_transport(*args, **kwargs):
        return httpx.MockTransport(handler)

    monkeypatch.setattr(scraper_service.httpx, "AsyncHTTPTransport", mock_transport)
    monkeypatch.setattr(scraper_service, "load_config", lambda: {platform: {"Acme": "acme"}})

    jobs = asyncio.run(scraper_service.scrape_jobs(companies=["Acme"], role_keys=None))

    label = f"{platform}/Acme"
    assert not any(j.get("company") == "Acme" for j in jobs)
    errors = scraper_service.LAST_SOURCE_REPORT["errors"]
    assert label in errors, f"{label} failure was swallowed; errors={errors}"
