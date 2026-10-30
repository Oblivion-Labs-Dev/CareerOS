""""Are you an employee of X?" without "currently" is still a current-employment check.

FanDuel asks "Are you an employee of Flutter or a Flutter brand?". The
COMPANY_HISTORY pattern required "currently"/"presently", so this classified
UNKNOWN and sent the application to review (2026-10-30).
"""

from app.services.application_assistant.profile_answer_resolver import resolve_answer

PROFILE = {"workExperience": [{"company": "Microsoft", "current": True}]}


def test_employee_of_unrelated_company_is_no():
    res = resolve_answer("Are you an employee of Flutter or a Flutter brand?", PROFILE, options=["Yes", "No"])
    assert res.question_type == "COMPANY_HISTORY"
    assert res.answer == "No"


def test_employee_of_current_employer_is_yes():
    res = resolve_answer("Are you an employee of Microsoft?", PROFILE, options=["Yes", "No"])
    assert res.answer == "Yes"
