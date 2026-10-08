"""Jobs found through Indeed/LinkedIn/HN get the employer's application link, not the listing."""

from __future__ import annotations

import pytest

from app.db.store import session_scope
from app.services.application_assistant.persistence import (
    list_autopilot_jobs,
    save_autopilot_job,
    upsert_discovered_job,
)
from app.services.application_assistant.scraper_import import applyable_url, scraper_job_to_aa_job
from app.services.job_discover import aggregator_resolve
from app.services.job_discover import store as jd_store

INDEED = "https://www.indeed.com/viewjob?jk={}"
REASON = "Application URL '{}' is an aggregator listing page, not an employer application form"


def test_the_employer_link_is_preferred_over_the_aggregator_listing():
    job = {"id": "s1", "url": INDEED.format("a1"), "applyUrl": "https://www.amazon.jobs/jobs/10569931/sde", "title": "SDE", "companyName": "amazon"}
    aa = scraper_job_to_aa_job(job)
    assert aa["applicationUrl"] == "https://www.amazon.jobs/jobs/10569931/sde"
    assert aa["listingUrl"] == INDEED.format("a1")
    assert applyable_url({"url": INDEED.format("a2"), "applyUrl": INDEED.format("a2")}) == INDEED.format("a2")
    assert applyable_url({"url": "https://boards.greenhouse.io/acme/jobs/1"}) == "https://boards.greenhouse.io/acme/jobs/1"


def test_listings_without_a_slug_are_looked_up_by_company_and_title(monkeypatch):
    calls = []
    monkeypatch.setattr(aggregator_resolve, "resolve_by_company_and_title", lambda c, t: calls.append(("ct", c, t)) or {"applicationUrl": "x"})
    monkeypatch.setattr(aggregator_resolve, "resolve_aggregator_url", lambda u, **kw: calls.append(("slug", u)) or None)
    aggregator_resolve.resolve_listing_url(INDEED.format("b"), company_name="Rippling", title="Senior SWE")
    aggregator_resolve.resolve_listing_url("https://himalayas.app/companies/torc/jobs/x", company_name="Torc", title="T")
    assert calls == [("ct", "Rippling", "Senior SWE"), ("slug", "https://himalayas.app/companies/torc/jobs/x")]


def _skipped(n: str, url: str, reason: str | None = None) -> dict:
    return {"id": f"apjob_t{n}", "jobId": f"aa_t{n}", "company": f"Co{n}", "title": f"Engineer {n}", "applicationUrl": url,
            "status": "SKIPPED", "skipReason": reason if reason is not None else REASON.format(url), "matchScore": 70}


def test_jobs_skipped_only_for_their_listing_link_are_requeued_at_the_employer_form(monkeypatch):
    from app.routers.application_assistant.autopilot import resolve_aggregator_urls

    redirect = "https://jsv3.recruitics.com/redirect?rx_job={}"
    scraped = {
        "s1": {"id": "s1", "url": INDEED.format("1"), "applyUrl": redirect.format("111")},
        "s2": {"id": "s2", "url": INDEED.format("2"), "applyUrl": redirect.format("222")},
        "s3": {"id": "s3", "url": INDEED.format("3"), "applyUrl": "https://boards.greenhouse.io/acme/jobs/9001"},
    }
    monkeypatch.setattr(jd_store, "get_snapshot", lambda _db: {"jobs": list(scraped.values())})
    monkeypatch.setattr(aggregator_resolve, "resolve_by_company_and_title", lambda c, t: None)
    rows = [
        _skipped("1", INDEED.format("1")),
        _skipped("2", INDEED.format("2")),
        _skipped("3", INDEED.format("3")),
        _skipped("4", INDEED.format("4")),
        _skipped("5", INDEED.format("5"), reason="Role 'Sales Lead' is not a Software Engineering role"),
        {"id": "apjob_t6", "jobId": "aa_t6", "company": "Acme", "title": "Engineer", "status": "SUBMITTED",
         "applicationUrl": "https://job-boards.greenhouse.io/acme/jobs/9001"},
    ]
    with session_scope() as db:
        for n in ("1", "2", "3"):
            upsert_discovered_job(db, {"id": f"aa_t{n}", "scraperJobId": f"s{n}", "company": "C", "title": "T", "applicationUrl": INDEED.format(n)})
        for row in rows:
            save_autopilot_job(db, row)

    with session_scope() as db:
        result = resolve_aggregator_urls(payload={}, db=db)
    with session_scope() as db:
        by_id = {j["id"]: j for j in list_autopilot_jobs(db) if j["id"].startswith("apjob_t")}

    assert result["resolved"] == 2 and result["duplicates"] == 1 and result["unresolved"] == 1
    for n, rx in (("1", "111"), ("2", "222")):
        job = by_id[f"apjob_t{n}"]
        assert job["status"] == "QUEUED" and job["applicationUrl"] == redirect.format(rx), "postings keyed by query are distinct"
        assert job["aggregatorUrl"] == INDEED.format(n) and not job.get("skipReason")
    assert by_id["apjob_t3"]["status"] != "QUEUED", "same Greenhouse posting as the submitted one"
    assert by_id["apjob_t4"]["status"] == "SKIPPED" and by_id["apjob_t4"]["applicationUrl"] == INDEED.format("4")
    assert by_id["apjob_t5"]["status"] == "SKIPPED", "skipped for a reason other than the link"
