"""Markets job-link validation: Workday link repair and live link checks."""

from __future__ import annotations

import httpx
import pytest

from app.db.store import session_scope
from app.services.job_discover.freshness import check_job_url_freshness
from app.services.markets import links

BOARDS = {"nvidia.wd5.myworkdayjobs.com": "NVIDIAExternalCareerSite"}
BROKEN = "https://nvidia.wd5.myworkdayjobs.com/job/US-WA-Redmond/Senior-Engineer_JR1"


def test_workday_links_without_their_career_site_are_repaired():
    assert links.repair_url(BROKEN, BOARDS) == "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-WA-Redmond/Senior-Engineer_JR1"
    fixed = links.repair_url(BROKEN, BOARDS)
    assert links.repair_url(fixed, BOARDS) == fixed
    assert links.repair_url("https://boards.greenhouse.io/acme/jobs/1", BOARDS) == "https://boards.greenhouse.io/acme/jobs/1"
    assert links.repair_url("https://other.wd1.myworkdayjobs.com/job/X_1", BOARDS) == "https://other.wd1.myworkdayjobs.com/job/X_1"


def test_workday_boards_come_from_company_career_config():
    companies = [
        {"career": {"provider": "workday", "config": {"host": "NVIDIA.wd5.myworkdayjobs.com", "board": "NVIDIAExternalCareerSite"}}},
        {"career": {"provider": "greenhouse", "config": {"board": "acme"}}},
        {"career": {}},
    ]
    assert links.workday_boards(companies) == {"nvidia.wd5.myworkdayjobs.com": "NVIDIAExternalCareerSite"}


@pytest.mark.anyio
async def test_closed_text_inside_page_scripts_is_not_a_closed_job():
    page = '<html><script>{"page_not_exists":"The page you are looking for no longer exists."}</script><h1>Senior Engineer</h1></html>'
    gone = "<html><body><p>This job is no longer available.</p></body></html>"

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=gone if request.url.path == "/gone" else page)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert not (await check_job_url_freshness("https://jobs.example/open", client))["closed"]
        assert (await check_job_url_freshness("https://jobs.example/gone", client))["closed"]


def _site(calls: list[str]):
    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        code = {"/open": 200, "/gone": 404, "/blocked": 403}[request.url.path]
        return httpx.Response(code, text="<h1>Job</h1>")
    return httpx.MockTransport(respond)


@pytest.mark.anyio
async def test_link_check_classifies_caches_and_forgets_unlisted_links():
    market = "linktest"
    urls = [f"https://jobs.example/{p}" for p in ("open", "gone", "blocked")]
    calls: list[str] = []
    async with httpx.AsyncClient(transport=_site(calls)) as client:
        progress = await links.check_links(market, urls, client=client)
        assert progress["done"] == 3 and progress["dead"] == 1 and not progress["running"]
        with session_scope() as db:
            stored = links.get_links(db, market)
        assert {u.rsplit("/", 1)[1]: v["status"] for u, v in stored.items()} == {"open": "ok", "gone": "dead", "blocked": "unknown"}
        assert "404" in stored[urls[1]]["reason"]

        calls.clear()
        again = await links.check_links(market, urls, client=client)
        assert again["total"] == 1 and all(c.endswith("/blocked") for c in calls), "only inconclusive results are re-fetched"
        await links.check_links(market, urls[:2], client=client)
        with session_scope() as db:
            assert set(links.get_links(db, market)) == set(urls[:2]), "links no longer listed are dropped"

        forced = await links.check_links(market, urls[:1], force=True, client=client)
        assert forced["total"] == 1 and calls


@pytest.mark.anyio
async def test_greenhouse_links_are_checked_through_the_board_api():
    assert links.probe_url("https://job-boards.greenhouse.io/acme/jobs/42?gh_src=x") == "https://boards-api.greenhouse.io/v1/boards/acme/jobs/42"
    assert links.probe_url("https://stripe.com/jobs/search?gh_jid=1") == "https://stripe.com/jobs/search?gh_jid=1"
    seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(404 if request.url.path.endswith("/7") else 200, json={})

    urls = ["https://boards.greenhouse.io/acme/jobs/7", "https://job-boards.greenhouse.io/acme/jobs/8"]
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await links.check_links("greenhouse", urls, client=client)
    assert all(u.startswith("https://boards-api.greenhouse.io/") for u in seen)
    with session_scope() as db:
        stored = links.get_links(db, "greenhouse")
    assert stored[urls[0]]["status"] == "dead" and stored[urls[1]]["status"] == "ok"


def test_stored_workday_links_are_rewritten_once(monkeypatch):
    from app.services.job_discover import store

    snapshot = {"jobs": [{"id": "a", "url": BROKEN, "applyUrl": BROKEN, "canonicalUrl": BROKEN},
                         {"id": "b", "url": "https://boards.greenhouse.io/acme/jobs/1"}]}
    saved: list[dict] = []
    monkeypatch.setattr(store, "_load_snapshot", lambda _db: saved[-1] if saved else snapshot)
    monkeypatch.setattr(store, "_persist_snapshot", lambda _db, snap: saved.append(snap))
    companies = [{"career": {"provider": "workday", "config": {"host": "nvidia.wd5.myworkdayjobs.com", "board": "NVIDIAExternalCareerSite"}}}]

    assert links.repair_stored_urls(None, companies) == 1
    job = saved[-1]["jobs"][0]
    assert job["url"] == job["applyUrl"] == job["canonicalUrl"] == links.repair_url(BROKEN, BOARDS)
    assert saved[-1]["jobs"][1] == snapshot["jobs"][1]
    assert links.repair_stored_urls(None, companies) == 0 and len(saved) == 1
