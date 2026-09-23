"""POST /api/jobs/import/batch - external job ingestion through the scraper's own pipeline."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.store import session_scope
from app.main import app
from app.services.job_discover import store as jd_store

TOKEN = "test-import-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _job(n: int, **overrides):
    job = {
        "source": "sutra-manthan",
        "external_id": f"ext-{n}",
        "title": f"Senior Software Engineer {n}",
        "company": f"Importco {n}",
        "location": "Seattle, WA",
        "url": f"https://boards.greenhouse.io/importco{n}/jobs/{9000 + n}",
        "description": "Build distributed backend systems in Python and Go.",
        "posted_at": "2026-09-22T10:00:00Z",
        "discovered_at": "2026-09-23T08:00:00Z",
    }
    job.update(overrides)
    return job


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "careeros_import_api_token", TOKEN)
    with TestClient(app) as test_client:
        yield test_client


def _post(client, jobs, headers=AUTH):
    return client.post("/api/jobs/import/batch", json={"jobs": jobs}, headers=headers)


def _snapshot_ids() -> set[str]:
    with session_scope() as db:
        return {job.get("id") for job in jd_store.get_snapshot(db).get("jobs") or []}


# ── authentication ──────────────────────────────────────────────────────────

def test_a_missing_token_is_rejected(client):
    assert _post(client, [_job(1)], headers={}).status_code == 401


def test_a_wrong_token_is_rejected(client):
    assert _post(client, [_job(1)], headers={"Authorization": "Bearer nope"}).status_code == 401


def test_the_endpoint_is_disabled_until_a_token_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "careeros_import_api_token", "")
    with TestClient(app) as test_client:
        assert _post(test_client, [_job(1)]).status_code == 503


def test_the_session_login_gate_does_not_block_the_token_holder(client, monkeypatch):
    from app.middleware import auth as auth_middleware

    monkeypatch.setattr(auth_middleware, "is_auth_configured", lambda: True)
    # No session cookie at all - only the import token.
    response = _post(client, [_job(40)])
    assert response.status_code == 200
    # ...while an ordinary endpoint still demands a session.
    assert client.get("/profile").status_code == 401


# ── imports ─────────────────────────────────────────────────────────────────

def test_new_jobs_are_created_and_land_in_the_discovery_snapshot(client):
    response = _post(client, [_job(2), _job(3)])

    body = response.json()
    assert response.status_code == 200
    assert body["summary"]["created"] == 2
    ids = [result["jobId"] for result in body["results"]]
    assert all(ids)
    assert set(ids) <= _snapshot_ids()
    assert [r["externalId"] for r in body["results"]] == ["ext-2", "ext-3"]


def test_resending_the_same_batch_is_idempotent(client):
    first = _post(client, [_job(4), _job(5)]).json()
    before = _snapshot_ids()
    second = _post(client, [_job(4), _job(5)]).json()

    assert second["summary"]["existing"] == 2
    assert second["summary"]["created"] == 0
    assert [r["jobId"] for r in second["results"]] == [r["jobId"] for r in first["results"]]
    assert _snapshot_ids() == before


def test_a_duplicate_within_one_batch_is_created_once(client):
    body = _post(client, [_job(6), _job(6)]).json()

    assert [r["status"] for r in body["results"]] == ["created", "existing"]
    assert body["results"][0]["jobId"] == body["results"][1]["jobId"]


def test_a_reimport_that_enriches_the_record_is_reported_as_updated(client):
    _post(client, [_job(7, description="")])
    body = _post(client, [_job(7)]).json()

    assert body["summary"]["updated"] == 1


def test_a_same_source_reimport_keeps_the_stored_fields_as_the_merge_rules_say(client):
    """CareerOS's merge (merge_job_records) keeps the stored record's primary
    fields unless the newcomer comes from a higher-priority source; the import
    reports what actually happened rather than overriding that rule."""
    _post(client, [_job(8)])
    body = _post(client, [_job(8, description="Now also Kubernetes and Terraform.")]).json()

    assert body["summary"]["existing"] == 1


def test_one_malformed_job_does_not_fail_the_batch(client):
    body = _post(client, [
        _job(14),
        {"source": "sutra-manthan", "title": "No company or url"},
        _job(9, url="not-a-url"),
        _job(10, posted_at="yesterday-ish"),
        "not even an object",
    ]).json()

    statuses = [r["status"] for r in body["results"]]
    assert statuses == ["created", "invalid", "invalid", "invalid", "invalid"]
    assert "company" in body["results"][1]["reason"]
    assert "url" in body["results"][2]["reason"]
    summary = dict(body["summary"])
    summary.pop("queued")
    assert summary == {"created": 1, "existing": 0, "updated": 0, "invalid": 4, "failed": 0, "total": 5}


def test_a_job_that_breaks_normalization_fails_alone(client, monkeypatch):
    real = jd_store._normalize_scraped_job

    def flaky(raw):
        if raw.get("externalId") == "ext-12":
            raise RuntimeError("boom")
        return real(raw)

    monkeypatch.setattr(jd_store, "_normalize_scraped_job", flaky)
    body = _post(client, [_job(11), _job(12), _job(13)]).json()

    assert [r["status"] for r in body["results"]] == ["created", "failed", "created"]
    assert "boom" in body["results"][1]["reason"]


def test_an_oversized_batch_is_refused(client, monkeypatch):
    from app.routers import job_import

    monkeypatch.setattr(job_import, "MAX_IMPORT_BATCH", 2)
    assert _post(client, [_job(20), _job(21), _job(22)]).status_code == 413


def test_imported_jobs_enter_the_normal_preprocessor_path(client):
    """The queue preprocessor ingests the snapshot, so imports need no path of their own."""
    from app.services.application_assistant.persistence import list_discovered_jobs
    from app.services.application_assistant.queue_preprocessor import QueuePreprocessor

    job_id = _post(client, [_job(30)]).json()["results"][0]["jobId"]
    QueuePreprocessor.get_instance()._ingest_scraper_snapshot()

    with session_scope() as db:
        discovered = list_discovered_jobs(db, active_only=False, exclude_demo=False)
    # scraper_job_to_aa_job links each discovered row to its snapshot job.
    assert any(d.get("scraperJobId") == job_id for d in discovered)


# ── straight into the Autopilot queue ───────────────────────────────────────

def _autopilot_rows(job_id):
    from app.services.application_assistant.persistence import list_autopilot_jobs
    from app.services.application_assistant.scraper_import import aa_job_id_for_scraper

    with session_scope() as db:
        return [j for j in list_autopilot_jobs(db) if j.get("jobId") == aa_job_id_for_scraper(job_id)]


def test_imported_jobs_are_queued_immediately_even_when_the_queue_is_full(client, monkeypatch):
    from app.services.application_assistant import queue_preprocessor

    # As if the queue were already past its intake watermark.
    monkeypatch.setattr(queue_preprocessor, "HIGH_QUEUE_WATERMARK", 0)
    monkeypatch.setattr(queue_preprocessor, "LOW_QUEUE_WATERMARK", -1)
    body = _post(client, [_job(50)]).json()

    result = body["results"][0]
    assert result["queued"] is True
    assert result["autopilotStatus"] == "QUEUED"
    assert body["summary"]["queued"] == 1
    assert [row["status"] for row in _autopilot_rows(result["jobId"])] == ["QUEUED"]


def test_reimporting_does_not_queue_a_job_twice(client):
    first = _post(client, [_job(51)]).json()["results"][0]
    second = _post(client, [_job(51)]).json()["results"][0]

    assert second["status"] == "existing"
    assert second["autopilotJobId"] == first["autopilotJobId"]
    assert len(_autopilot_rows(first["jobId"])) == 1


def test_an_import_that_fails_the_hard_filters_is_not_queued(client):
    body = _post(client, [_job(52, title="Director of Engineering", location="Berlin, Germany",
                               description="Must be a US citizen with an active security clearance.")]).json()

    result = body["results"][0]
    assert result["status"] == "created"
    assert result["queued"] is False
