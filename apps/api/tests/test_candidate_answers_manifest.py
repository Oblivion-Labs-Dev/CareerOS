import pytest
from app.services.application_assistant.profile_answer_resolver import resolve_answer

@pytest.fixture
def empty_profile():
    return {
        "fullName": "Akshay Borse",
        "email": "amsborse@gmail.com",
        "phone": "4253369852",
        "city": "Auburn",
        "state": "WA",
        "workAuth": {"authorizedToWorkInUS": True, "requiresSponsorshipNowOrFuture": False},
    }

def test_manifest_resolves_high_school_math(empty_profile):
    res = resolve_answer("How did you perform in mathematics at high school?*", empty_profile)
    assert res.answer == "Top 0.01%"
    assert res.resolution_method in ("CANDIDATE_MANIFEST", "PROFILE_SCREENING_ANSWER")

def test_manifest_resolves_native_language(empty_profile):
    res = resolve_answer("How did you perform in your native language at high school?*", empty_profile)
    assert res.answer == "Top 1% at my school"
    assert res.resolution_method in ("CANDIDATE_MANIFEST", "PROFILE_SCREENING_ANSWER")

def test_manifest_resolves_companies(empty_profile):
    res = resolve_answer("In the past ten years, looking only at the time since you graduated your first undergraduate degree, how many companies have you worked for?*", empty_profile)
    assert res.answer == "2"

def test_manifest_resolves_kubernetes(empty_profile):
    res = resolve_answer("In Kubernetes, what is the difference between a Pod and a Container?", empty_profile)
    assert "isolated environment" in res.answer
    assert "smallest deployable unit" in res.answer

def test_manifest_resolves_databases(empty_profile):
    res = resolve_answer("Which databases do you have experience using? With which are you most familiar?", empty_profile)
    assert "PostgreSQL" in res.answer
    assert "DynamoDB" in res.answer

def test_manifest_resolves_relocation(empty_profile):
    res = resolve_answer("Are you open to relocating now or in the near future?*", empty_profile, options=["Yes", "No"])
    assert res.answer == "Yes"

def test_manifest_resolves_startup_hours(empty_profile):
    res = resolve_answer("Kalepa is a growth stage startup... As a result, we find ourselves working more than the standard 40 hours a week. Are you interested in being in such environment?*", empty_profile, options=["Yes", "No"])
    assert res.answer == "Yes"

def test_manifest_resolves_education_school(empty_profile):
    res = resolve_answer("School*", empty_profile)
    assert res.answer == "Santa Clara University"
