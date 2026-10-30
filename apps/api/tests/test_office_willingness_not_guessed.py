""""Willing to work from the office(s) listed?" is not answered from residence.

Found on the 2026-10-30 night loop: a form asks "Are you willing to work from
the office(s) listed on the job description?" without naming the office. The
question was resolved as a residence check, which can only see the question
text, so it answered "No" for every posting — including a Bellevue, WA role
twenty miles from the candidate's home, and in contradiction of their saved
"willing to relocate" answers. Willingness is the candidate's preference and the
office is not in the question, so it is left for the candidate until they set a
rule for it.
"""

from app.services.application_assistant.profile_answer_resolver import resolve_answer

PROFILE = {"city": "Auburn", "state": "Washington", "country": "United States", "relocate": "Yes"}
Q = "Are you willing to work from the office(s) listed on the job description?"


def test_office_willingness_is_not_answered_no():
    res = resolve_answer(Q, PROFILE, options=["Yes", "No"])
    assert res.answer != "No"


def test_residence_question_still_answered_from_profile():
    res = resolve_answer("Are you located in Washington state?", PROFILE, options=["Yes", "No"])
    assert res.answer == "Yes"
