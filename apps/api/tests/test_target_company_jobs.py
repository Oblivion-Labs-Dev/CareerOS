from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

DOCUSIGN_SAMPLE = {
    "jobs": [
        {
            "data": {
                "req_id": "29452",
                "title": "Senior Software Engineer",
                "location_name": "San Francisco, California, United States",
                "country_code": "US",
            }
        },
        {
            "data": {
                "req_id": "99999",
                "title": "Recruiter",
                "location_name": "Seattle, Washington, United States",
                "country_code": "US",
            }
        },
    ]
}


def test_filter_jobs_remote_and_washington() -> None:
    from app.services.target_company_jobs import filter_jobs

    jobs = [
        {"company": "Oracle", "title": "A", "tags": ["remote"], "active": True},
        {"company": "Oracle", "title": "B", "tags": ["washington"], "active": True},
        {"company": "Oracle", "title": "C", "tags": ["us"], "active": True},
    ]
    assert len(filter_jobs(jobs, location="remote")) == 1
    assert len(filter_jobs(jobs, location="washington")) == 2


def test_refresh_target_company_jobs_route() -> None:
    with patch("app.services.target_company_jobs.fetch_docusign_jobs") as mock_doc:
        with patch("app.services.target_company_jobs.fetch_oracle_jobs") as mock_oracle:
            mock_doc.return_value = [
                {
                    "id": "29452",
                    "company": "DocuSign",
                    "title": "Senior Software Engineer",
                    "location": "Seattle, WA",
                    "url": "https://example.com/29452",
                    "tags": ["washington", "us"],
                    "active": True,
                }
            ]
            mock_oracle.return_value = [
                {
                    "id": "338844",
                    "company": "Oracle",
                    "title": "Senior Software Development Engineer",
                    "location": "United States (Remote)",
                    "url": "https://example.com/338844",
                    "tags": ["remote", "us"],
                    "active": True,
                }
            ]
            response = client.post("/jobs/target-companies/refresh", json={"verifyOracle": False})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["totalJobs"] == 2

    listed = client.get("/jobs/target-companies?company=Oracle&location=remote")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def test_whatsapp_endpoint() -> None:
    client.post("/jobs/target-companies/refresh", json={"verifyOracle": False})
    response = client.get("/jobs/target-companies/whatsapp?company=all&location=all")
    assert response.status_code == 200
    body = response.json()
    assert "text" in body
    assert "*Target company jobs*" in body["text"] or "Target company jobs" in body["text"]


def test_fetch_docusign_filters_senior_software() -> None:
    from app.services.target_company_jobs import fetch_docusign_jobs

    with patch("app.services.target_company_jobs._http_get_json", return_value=DOCUSIGN_SAMPLE):
        jobs = fetch_docusign_jobs()
    assert len(jobs) == 1
    assert jobs[0]["id"] == "29452"
