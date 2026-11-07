"""A new account's onboarding must ask everything an application needs.

Every blocking readiness gap stops a run before any form is filled, so a gap
the wizard never asks about leaves a new user stuck with no way forward but
hunting through the profile page. All values here are fictional.
"""

from app.routers.onboarding import ONBOARDING_SECTIONS
from app.services.application_assistant.profile_readiness import evaluate_profile_readiness


def _asked_keys() -> set[str]:
    keys: set[str] = set()
    for section in ONBOARDING_SECTIONS:
        for question in section["questions"]:
            keys.add(question["key"])
            keys.update(question.get("covers", []))
    return keys


def test_every_blocking_gap_of_an_empty_profile_is_asked_by_onboarding():
    gaps = evaluate_profile_readiness({}).blocking
    missing = sorted({gap.profile_key for gap in gaps} - _asked_keys())
    assert missing == [], f"blocking gaps the wizard never asks: {missing}"


def test_missing_contact_details_block_readiness():
    keys = {gap.profile_key for gap in evaluate_profile_readiness({}).blocking}
    assert {"fullName", "email", "phone"} <= keys


def test_contact_details_from_signup_are_not_asked_again():
    profile = {"fullName": "Jordan Lee", "email": "jordan.lee@example.com", "phone": "(512) 555-0199"}
    keys = {gap.profile_key for gap in evaluate_profile_readiness(profile).blocking}
    assert not keys & {"fullName", "email", "phone"}


def test_a_first_and_last_name_count_as_a_name():
    profile = {"firstName": "Jordan", "lastName": "Lee", "email": "j@example.com", "phone": "5125550199"}
    keys = {gap.profile_key for gap in evaluate_profile_readiness(profile).blocking}
    assert "fullName" not in keys


def test_the_resume_step_comes_first_so_it_can_prefill_the_rest():
    first = ONBOARDING_SECTIONS[0]
    resume = next(q for q in first["questions"] if q["type"] == "resume")
    assert {"workExperience", "education"} <= set(resume["covers"])
