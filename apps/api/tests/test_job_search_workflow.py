"""Tests for ai-job-search patterns ported into CareerOS."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.job_search.cover_letter_pipeline import generate_cover_letter_with_review
from app.services.job_search.html_report import build_analytics_summary, render_html_report
from app.services.job_search.job_evaluation import evaluate_job_fit, rank_jobs
from app.services.job_search.outcome_archive import render_outcome_markdown, write_outcome_archive

client = TestClient(app)

SAMPLE_PROFILE = {
    "fullName": "Alex Rivera",
    "currentTitle": "Software Engineer",
    "targetRole": "Senior Software Engineer",
    "yearsExperience": 6,
    "skills": "python, react, aws, docker",
    "city": "Seattle",
    "state": "WA",
    "workAuthorization": "h1b needs sponsorship",
}

SAMPLE_JOB = {
    "id": "job_test_1",
    "title": "Senior Software Engineer",
    "companyName": "Acme Corp",
    "location": "Seattle, WA (Hybrid)",
    "description": (
        "We need a senior software engineer with Python, React, and AWS experience. "
        "Strong communication and cross-functional collaboration required. Remote-friendly hybrid schedule."
    ),
    "url": "https://example.com/jobs/1",
}


def test_evaluate_job_fit_returns_dimensions() -> None:
    result = evaluate_job_fit(SAMPLE_JOB, SAMPLE_PROFILE)
    assert result["eligible"] is True
    assert result["location"] == "PASS"
    assert 0 <= result["overallScore"] <= 100
    assert result["verdict"] in {"Strong Fit", "Good Fit", "Moderate Fit", "Weak Fit", "Poor Fit"}
    assert "technical" in result["scores"]
    assert isinstance(result["strengths"], list)
    assert "legitimacy" in result
    assert result["legitimacy"]["block"] == "G"


def test_evaluate_job_fit_vetoes_relocation() -> None:
    job = {
        **SAMPLE_JOB,
        "location": "Austin, TX",
        "description": "On-site only. Relocation required. Must relocate within 30 days.",
    }
    result = evaluate_job_fit(job, SAMPLE_PROFILE)
    assert result["location"] == "FAIL"
    assert result["verdict"] in {"Weak Fit", "Poor Fit", "Moderate Fit"}


def test_rank_jobs_excludes_applied() -> None:
    jobs = [SAMPLE_JOB, {**SAMPLE_JOB, "id": "job_2", "title": "Staff Engineer"}]
    exclude = {"acme corp|senior software engineer"}
    ranked = rank_jobs(jobs, SAMPLE_PROFILE, exclude_applied=exclude)
    assert len(ranked) == 1
    assert ranked[0]["title"] == "Staff Engineer"
    assert "fitEvaluation" in ranked[0]


def test_cover_letter_template_pipeline() -> None:
    import asyncio

    result = asyncio.run(
        generate_cover_letter_with_review(
            SAMPLE_PROFILE,
            company="Acme Corp",
            role="Senior Software Engineer",
            job_description=SAMPLE_JOB["description"],
            use_llm=False,
        )
    )
    assert result["pipelineMode"] == "template"
    assert "Acme Corp" in result["content"]
    assert "Senior Software Engineer" in result["content"]


def test_outcome_archive_roundtrip(tmp_path, monkeypatch) -> None:
    import app.services.job_search.outcome_archive as archive_mod

    monkeypatch.setattr(archive_mod, "ARCHIVE_ROOT", tmp_path)

    application = {
        "id": "app_1",
        "companyName": "Acme Corp",
        "roleTitle": "Senior Software Engineer",
        "notes": "Applied via referral",
    }
    archive = write_outcome_archive(
        application,
        status="in_progress",
        notes="Waiting for recruiter response",
        job_posting="Full posting text here",
    )
    assert archive["archivePath"]
    markdown = render_outcome_markdown(
        company="Acme Corp",
        role="Senior Software Engineer",
        status="rejected",
        notes="No response after 3 weeks",
        date_resolved="2026-07-01",
    )
    assert "**Status:** rejected" in markdown
    assert "2026-07-01" in markdown


def test_html_report_renders() -> None:
    applications = [
        {
            "companyName": "Acme Corp",
            "roleTitle": "Senior Software Engineer",
            "status": "interviewing",
            "platform": "greenhouse",
            "source": "scraper",
            "notes": "Phone screen scheduled",
            "createdAt": "2026-07-01T00:00:00Z",
            "url": "https://example.com/jobs/1",
        },
        {
            "companyName": "Beta Inc",
            "roleTitle": "Software Engineer",
            "status": "rejected",
            "platform": "lever",
            "source": "referral",
            "notes": "Not a fit",
            "createdAt": "2026-06-15T00:00:00Z",
        },
    ]
    summary = build_analytics_summary(applications)
    assert summary["total"] == 2
    assert summary["buckets"]["Interview"] == 1
    html = render_html_report(applications)
    assert "Job Search Dashboard" in html
    assert "Acme Corp" in html


def test_evaluate_fit_api() -> None:
    response = client.post("/jobs/evaluate-fit", json={"job": SAMPLE_JOB})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "evaluation" in body


def test_analytics_summary_api() -> None:
    response = client.get("/analytics/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "summary" in body
    assert "marketTrends" in body


def test_market_trends_api() -> None:
    response = client.get("/analytics/market-trends?country=US")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "marketTrends" in body


def test_analytics_html_report_api() -> None:
    response = client.get("/analytics/report")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Job Search Dashboard" in response.text


def test_cover_letter_generate_api_uses_pipeline() -> None:
    response = client.post(
        "/cover-letter/generate",
        json={
            "companyName": "Acme Corp",
            "roleTitle": "Senior Software Engineer",
            "jobDescription": SAMPLE_JOB["description"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    letter = body["coverLetter"]
    assert letter["content"]
    assert letter["pipelineMode"] in {"template", "drafter", "drafter-reviewer"}


def test_record_outcome_api(tmp_path, monkeypatch) -> None:
    import app.services.job_search.outcome_archive as archive_mod

    monkeypatch.setattr(archive_mod, "ARCHIVE_ROOT", tmp_path)

    create = client.post(
        "/applications",
        json={
            "application": {
                "companyName": "Outcome Test Co",
                "roleTitle": "Engineer",
                "status": "submitted",
                "url": "https://example.com/outcome",
            }
        },
    )
    assert create.status_code == 200
    app_id = create.json()["application"]["id"]

    response = client.post(
        f"/applications/{app_id}/outcome",
        json={
            "status": "rejected",
            "notes": "Closed after technical screen",
            "dateResolved": "2026-07-20",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["application"]["outcomeStatus"] == "rejected"
    assert body["archive"]["archivePath"]
