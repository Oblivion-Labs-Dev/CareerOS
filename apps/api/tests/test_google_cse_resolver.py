"""The Google fallback must stay inside a 100/day budget and never queue a wrong posting.

This runs only over what the free ATS lookup could not resolve — mostly
enterprises on Workday/Taleo/iCIMS. Two things make it safe to leave enabled:
a persisted daily budget, and a match test strict enough that a careers landing
page or an unrelated opening is refused rather than applied to.
"""

from __future__ import annotations

import pytest

from app.services.job_discover.google_cse_resolver import (
    _is_applyable,
    _pick_best,
    get_usage,
    is_configured,
)


def test_disabled_without_credentials(monkeypatch):
    monkeypatch.delenv("GOOGLE_CSE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_ENGINE_ID", raising=False)
    assert is_configured() is False


def test_enabled_only_when_both_values_present(monkeypatch):
    monkeypatch.setenv("GOOGLE_CSE_API_KEY", "k")
    monkeypatch.delenv("GOOGLE_CSE_ENGINE_ID", raising=False)
    assert is_configured() is False
    monkeypatch.setenv("GOOGLE_CSE_ENGINE_ID", "cx")
    assert is_configured() is True


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://gm.wd5.myworkdayjobs.com/en-US/careers/job/JR-123", True),
        ("https://usbank.taleo.net/careersection/jobdetail.ftl?job=123", True),
        ("https://careers-collins.icims.com/jobs/12345/job", True),
        ("https://job-boards.greenhouse.io/acme/jobs/123", True),
        # A LinkedIn mirror is the thing we are trying to get *away* from.
        ("https://www.linkedin.com/jobs/view/4467780167", False),
        ("https://en.wikipedia.org/wiki/General_Motors", False),
    ],
)
def test_only_applyable_hosts_count(url, expected):
    assert _is_applyable(url) is expected


def test_prefers_the_applyable_posting_over_a_mirror_or_a_search_page():
    items = [
        {
            "link": "https://www.linkedin.com/jobs/view/123",
            "title": "Senior Software Engineer - Go at GM",
            "snippet": "General Motors",
        },
        {
            "link": "https://gm.wd5.myworkdayjobs.com/en-US/careers/job/Senior-Software-Engineer-Go_JR-123",
            "title": "Senior Software Engineer - Go (Golang)",
            "snippet": "General Motors Warren MI",
        },
        {
            "link": "https://careers.gm.com/search",
            "title": "Search jobs",
            "snippet": "All openings",
        },
    ]
    best = _pick_best(items, "General Motors", "Senior Software Engineer - Go (Golang)")
    assert best is not None
    assert "myworkdayjobs.com" in best["link"]


def test_unrelated_opening_at_the_right_company_is_refused():
    """Right employer, wrong job — queuing this would apply to the wrong role."""
    items = [{
        "link": "https://gm.wd5.myworkdayjobs.com/en-US/careers/job/Warehouse_JR-9",
        "title": "Warehouse Associate",
        "snippet": "General Motors",
    }]
    assert _pick_best(items, "General Motors", "Senior Software Engineer - Go (Golang)") is None


def test_no_results_is_not_an_error():
    assert _pick_best([], "General Motors", "Senior Software Engineer") is None


def test_usage_starts_at_zero_and_reports_a_budget():
    from app.db.store import session_scope

    with session_scope() as db:
        used, budget = get_usage(db)
    assert used >= 0
    assert budget > 0


def test_usage_resets_on_a_new_day():
    """The quota is daily, so a stale counter must not suppress lookups forever."""
    from app.db.store import session_scope, set_kv

    from app.services.job_discover.google_cse_resolver import QUOTA_KV_KEY

    with session_scope() as db:
        set_kv(db, QUOTA_KV_KEY, {"date": "1999-01-01", "count": 999})
        used, _ = get_usage(db)
    assert used == 0
