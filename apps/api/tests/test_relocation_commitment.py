"""Relocation is a promise, so it must come from the profile — never a default.

A live Verkada posting asked "Our HQ is in San Mateo and this role is not
remote. Are you able to come onsite as required?" — a location commitment for a
Seattle candidate. It classified as WORK_ARRANGEMENT, whose resolver treats
everything as a schedule preference the candidate is flexible about, and
answered "Yes" with nothing on the profile to back it up.
"""

from app.services.application_assistant.profile_answer_resolver import resolve_answer

SEATTLE = {"city": "Seattle", "state": "Washington", "location": "Seattle, WA"}
WILLING = {**SEATTLE, "relocate": "Yes"}

ONSITE_ELSEWHERE = (
    "Our HQ is in San Mateo and this role is not remote. "
    "Are you able to come onsite as required for this role?*"
)
YES_NO = ["Yes", "No"]


class TestLocationCommitment:
    def test_onsite_elsewhere_is_unanswered_without_a_recorded_stance(self):
        result = resolve_answer(ONSITE_ELSEWHERE, SEATTLE, options=YES_NO, field_id="q")
        assert not result.answer

    def test_onsite_elsewhere_answers_yes_from_the_profile(self):
        result = resolve_answer(ONSITE_ELSEWHERE, WILLING, options=YES_NO, field_id="q")
        assert result.answer == "Yes"

    def test_willing_to_relocate_needs_the_profile_too(self):
        assert not resolve_answer("Are you willing to relocate?", SEATTLE, options=YES_NO).answer
        assert resolve_answer("Are you willing to relocate?", WILLING, options=YES_NO).answer == "Yes"

    def test_requiring_relocation_assistance_stays_no(self):
        # Opposite direction: being open to moving is not a request for the
        # employer to pay for it, and answering "No" commits to nothing.
        result = resolve_answer("Will you require relocation assistance?", WILLING, options=YES_NO)
        assert result.answer == "No"

    def test_a_plain_schedule_question_is_still_answerable(self):
        result = resolve_answer(
            "Are you comfortable with a hybrid schedule of 3 days per week in the office?",
            SEATTLE, options=YES_NO,
        )
        assert result.answer == "Yes"

    def test_onsite_in_the_candidates_own_city_is_answerable(self):
        result = resolve_answer(
            "Our office is in Seattle. Are you able to come onsite?", SEATTLE, options=YES_NO,
        )
        assert result.answer == "Yes"
