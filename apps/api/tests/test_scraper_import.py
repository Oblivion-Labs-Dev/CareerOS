"""Tests for scraper → Application Assistant import."""

from __future__ import annotations

import pytest

from app.db.store import session_scope, set_kv
from app.services.application_assistant.persistence import list_discovered_jobs
from app.services.application_assistant.scraper_import import (
    aa_job_id_for_scraper,
    import_scraper_job_by_id,
    import_scraper_job_record,
    scraper_job_to_aa_job,
    scraper_sync_status,
    sync_scraper_jobs,
)
from app.services.job_discover import store as jd_store


@pytest.fixture
def sample_scraper_job():
    return {
        "id": "reddit:8082867",
        "companyName": "reddit",
        "title": "Software Engineer",
        "location": "Remote",
        "url": "https://job-boards.greenhouse.io/reddit/jobs/8082867",
        "description": "Build things",
        "externalId": "8082867",
        "relevancyScore": 82,
        "keywordsMatched": ["python"],
        "scrapedAt": "2026-07-27T12:00:00Z",
    }


class TestScraperImportHelpers:
    def test_aa_job_id_for_scraper(self):
        assert aa_job_id_for_scraper("reddit:8082867") == "aa_reddit_8082867"

    def test_scraper_job_to_aa_job_detects_greenhouse(self, sample_scraper_job):
        aa_job = scraper_job_to_aa_job(sample_scraper_job)
        assert aa_job["id"] == "aa_reddit_8082867"
        assert aa_job["sourceProvider"] == "greenhouse"
        assert aa_job["discoveryRunId"] == "scraper_import"
        assert aa_job["scraperJobId"] == "reddit:8082867"
        assert aa_job["workplaceType"] == "remote"


class TestScraperImportPersistence:
    def test_import_marks_job_added_to_assistant(self, sample_scraper_job):
        with session_scope() as db:
            set_kv(db, "profile", {"headline": "Software Engineer", "skills": ["python"]})
            jd_store._persist_snapshot(db, {"jobs": [sample_scraper_job], "scrapedAt": "2026-01-01T00:00:00Z"})

            result = import_scraper_job_by_id(db, sample_scraper_job["id"])
            assert result["success"] is True
            assert result["job"]["addedToAssistant"] is True
            assert result["job"]["company"] == "Reddit"
            assert result["match"]["overallScore"] >= 0
            assert result.get("applicationId")
            assert result["application"]["jobId"] == "aa_reddit_8082867"

            jobs = list_discovered_jobs(db, active_only=False, exclude_demo=False)
            assert any(j["id"] == "aa_reddit_8082867" and j.get("addedToAssistant") for j in jobs)

            status = scraper_sync_status(db)
            assert status["scraperTotal"] == 1
            assert status["syncedTotal"] == 1
            assert status["pendingSync"] == 0

            unchanged = import_scraper_job_record(db, sample_scraper_job, rescore=False, mark_added=True)
            assert unchanged["action"] == "unchanged"

    def test_sync_only_refreshes_added_jobs(self, sample_scraper_job):
        with session_scope() as db:
            jd_store._persist_snapshot(db, {"jobs": [sample_scraper_job], "scrapedAt": "2026-01-01T00:00:00Z"})

            sync = sync_scraper_jobs(db)
            assert sync["success"] is True
            assert sync["processed"] == 0
            assert sync["syncedTotal"] == 0

            import_scraper_job_by_id(db, sample_scraper_job["id"])
            sync = sync_scraper_jobs(db)
            assert sync["processed"] == 1
            assert sync["syncedTotal"] == 1
