"""Tests for Candidate Onboarding Questionnaire Router."""

from fastapi.testclient import TestClient

from app.db.store import session_scope, set_kv
from app.main import app

client = TestClient(app)


def test_get_onboarding_questions() -> None:
    response = client.get("/api/onboarding/questions")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "sections" in data
    assert len(data["sections"]) >= 4

    section_ids = [s["id"] for s in data["sections"]]
    assert "work_auth" in section_ids
    assert "location_preferences" in section_ids
    assert "eeo_voluntary" in section_ids


def test_save_onboarding_answers() -> None:
    with session_scope() as db:
        set_kv(
            db,
            "profile",
            {
                "workExperience": [{"company": "Stripe", "jobTitle": "Engineer"}],
                "education": [{"school": "UW", "degree": "BS"}],
            },
        )

    answers_payload = {
        "answers": {
            "authorizedToWorkInUS": True,
            "sponsorship": False,
            "city": "Seattle",
            "state": "Washington",
            "zip": "98101",
            "targetRole": "Staff Software Engineer",
            "yearsExperience": 10,
            "workArrangement": "Remote",
            "relocate": "No",
            "englishLevel": "Fluent",
            "citizenshipCountry": "United States",
            "timezone": "America/Los_Angeles",
        }
    }

    response = client.post("/api/onboarding/answers", json=answers_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["profile"]["city"] == "Seattle"
    assert data["profile"]["state"] == "Washington"
    assert data["profile"]["workAuth"]["authorizedToWorkInUS"] is True
    assert data["profile"]["workAuth"]["requiresSponsorshipNowOrFuture"] is False
    assert data["isReady"] is True
