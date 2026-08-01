"""Tests for demo/test data filtering."""

from __future__ import annotations

from app.services.application_assistant.demo_data import is_demo_application, is_demo_company_name, is_demo_job


def test_is_demo_company_name() -> None:
    assert is_demo_company_name("Test Co")
    assert is_demo_company_name("Test Company")
    assert not is_demo_company_name("Reddit")


def test_is_demo_application() -> None:
    assert is_demo_application({"companyName": "Test Co", "jobId": "job_test", "jobUrl": "https://example.com/apply"})
    assert not is_demo_application({"companyName": "Reddit", "jobUrl": "https://boards.greenhouse.io/reddit/jobs/123"})


def test_is_demo_job() -> None:
    assert is_demo_job({"company": "Test Company", "applicationUrl": "http://127.0.0.1:8000/form"})
    assert not is_demo_job({"company": "SpaceX", "applicationUrl": "https://boards.greenhouse.io/spacex/jobs/1"})
