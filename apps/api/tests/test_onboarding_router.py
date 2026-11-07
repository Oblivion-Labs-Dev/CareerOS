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
            "fullName": "Jordan Lee",
            "email": "jordan.lee@example.com",
            "phone": "(512) 555-0199",
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


def test_the_resume_step_shows_an_uploaded_resume_and_is_never_saved_as_an_answer() -> None:
    with session_scope() as db:
        set_kv(db, "profile", {"fullName": "Jordan Lee"})
        set_kv(db, "documents", {"defaultResume": {"name": "jordan-lee.pdf", "base64": "JVBERi0="}})

    data = client.get("/api/onboarding/questions").json()
    assert data["currentValues"]["resume"] == "jordan-lee.pdf"
    assert data["sections"][0]["id"] == "contact_resume"

    saved = client.post("/api/onboarding/answers", json={"answers": {"resume": "jordan-lee.pdf", "phone": "5125550199"}}).json()
    assert "resume" not in saved["profile"]
    assert saved["profile"]["phone"] == "5125550199"


def test_the_resume_step_is_empty_without_an_upload() -> None:
    with session_scope() as db:
        set_kv(db, "profile", {})
        set_kv(db, "documents", {"defaultResume": None, "defaultCoverLetter": None})
    assert "resume" not in client.get("/api/onboarding/questions").json()["currentValues"]
