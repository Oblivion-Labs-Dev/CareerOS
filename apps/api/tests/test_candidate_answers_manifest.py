import pytest

pytestmark = pytest.mark.real_candidate_manifest

from app.services.application_assistant.profile_answer_resolver import resolve_answer

@pytest.fixture
def empty_profile():
    return {
        "fullName": "Akshay Borse",
        "email": "candidate@example.com",
        "phone": "2065550100",
        "city": "Auburn",
        "state": "WA",
        "workAuth": {"authorizedToWorkInUS": True, "requiresSponsorshipNowOrFuture": False},
    }

# Quarantined (confirmed_by_user: false) on 2026-10-07: unverified rankings, an
# employer count career.json contradicts, and databases it does not record.
@pytest.mark.parametrize("question", [
    "How did you perform in mathematics at high school?*",
    "How did you perform in your native language at high school?*",
    "In the past ten years, looking only at the time since you graduated your first undergraduate degree, "
    "how many companies have you worked for?*",
    "Which databases do you have experience using? With which are you most familiar?",
    "Street Address*",
])
def test_quarantined_manifest_entries_are_not_used(empty_profile, question):
    res = resolve_answer(question, empty_profile)
    assert res.resolution_method != "CANDIDATE_MANIFEST"

def test_manifest_resolves_kubernetes(empty_profile):
    res = resolve_answer("In Kubernetes, what is the difference between a Pod and a Container?", empty_profile)
    assert "isolated environment" in res.answer
    assert "smallest deployable unit" in res.answer

def test_manifest_resolves_relocation(empty_profile):
    res = resolve_answer("Are you open to relocating now or in the near future?*", empty_profile, options=["Yes", "No"])
    assert res.answer == "Yes"

def test_manifest_resolves_startup_hours(empty_profile):
    res = resolve_answer("Kalepa is a growth stage startup... As a result, we find ourselves working more than the standard 40 hours a week. Are you interested in being in such environment?*", empty_profile, options=["Yes", "No"])
    assert res.answer == "Yes"

def test_manifest_resolves_education_school(empty_profile):
    res = resolve_answer("School*", empty_profile)
    assert res.answer == "Santa Clara University"


# Manifest entries captured from option labels or shifted against their
# question must never be applied (all observed on real submissions, 2026-10-06).

def test_linkedin_url_field_is_not_answered_yes(empty_profile):
    # q_083 "Do you have a LinkedIn profile?" fuzzy-matched the URL field and
    # sent "Yes" as the LinkedIn URL on 13 applications.
    res = resolve_answer("LinkedIn Profile", empty_profile)
    assert res.answer != "Yes"


@pytest.mark.parametrize("label", ["Male", "Asian", "Black or African American", "I am a current employee"])
def test_option_label_entries_are_not_answers(empty_profile, label):
    res = resolve_answer(label, empty_profile, options=[label])
    assert res.resolution_method != "CANDIDATE_MANIFEST"


def test_misaligned_checkbox_entry_is_ignored(empty_profile):
    res = resolve_answer("Former Employee", empty_profile)
    assert "isolated environment" not in (res.answer or "")


def test_essay_entry_answered_yes_is_ignored(empty_profile):
    q = ("Describe one backend system you personally built or significantly contributed to that "
         "processed usage, events, transactions, or other high-volume data.*")
    res = resolve_answer(q, empty_profile)
    assert res.answer != "Yes"


def test_yes_no_question_captured_as_textarea_still_resolves(empty_profile):
    q = "Do you have a close personal relationship with a current Mastercard or Recorded Future employee? *"
    res = resolve_answer(q, empty_profile, options=["Yes", "No"])
    assert res.answer == "No"
