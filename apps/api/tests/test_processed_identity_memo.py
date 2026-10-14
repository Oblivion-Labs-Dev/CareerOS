"""Browse Jobs exclusion sets are rebuilt only when the cached job list changes.

They are derived from read_cache's autopilot job list; rebuilding ~8,000
composite keys on every stats/list/locations request cost ~300 ms. A memo keyed
on that list object must still pick up a newly queued job once the cache
refreshes, or Browse would keep showing a job already in the pipeline.
"""

from app.routers import api
from app.services.read_cache import read_cache


def _job(n: int) -> dict:
    return {
        "company": f"Acme {n}",
        "title": "Senior Software Engineer",
        "applicationUrl": f"https://boards.greenhouse.io/acme{n}/jobs/{1000 + n}",
        "status": "QUEUED",
    }


def test_identity_is_reused_until_the_cached_list_changes(monkeypatch):
    first = [_job(1)]
    current = {"jobs": first}
    monkeypatch.setattr(read_cache, "get", lambda key, ttl, loader: current["jobs"])
    monkeypatch.setattr(api, "_processed_identity_memo", None)

    a = api._processed_autopilot_identity(None)
    assert api._processed_autopilot_identity(None) is a

    current["jobs"] = [_job(1), _job(2)]
    keys, urls, _ = api._processed_autopilot_identity(None)
    assert keys is not a[0]
    assert any("acme2" in u for u in urls)


def test_identity_sets_are_read_only(monkeypatch):
    monkeypatch.setattr(read_cache, "get", lambda key, ttl, loader: [_job(1)])
    monkeypatch.setattr(api, "_processed_identity_memo", None)
    keys, urls, company_titles = api._processed_autopilot_identity(None)
    assert all(isinstance(s, frozenset) for s in (keys, urls, company_titles))
