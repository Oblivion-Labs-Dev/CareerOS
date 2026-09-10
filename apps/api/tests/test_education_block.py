"""Greenhouse education block: classification and positional resolution.

Regression cover for two defects seen on a live Affirm posting: "Start date
year" inside the education block was classified NOTICE_PERIOD (so an education
field would have been answered with the candidate's availability to start a
job), and "End date year" had no resolver at all, leaving a required field
empty and staging the application for review.
"""

from app.services.application_assistant.profile_answer_resolver import (
    _education_field,
    resolve_answer,
)
from app.services.application_assistant.question_classifier import (
    QuestionType,
    classify_question,
)

PROFILE = {
    "education": [
        {
            "school": "Santa Clara University",
            "degree": "Master's Degree",
            "discipline": "Computer Science",
            "startDate": "09/2017",
            "endDate": "06/2019",
        },
        {
            "school": "Pune Institute of Computer Technology",
            "degree": "Bachelor's Degree",
            "discipline": "Computer Science",
            "startDate": "06/2012",
            "endDate": "06/2016",
        },
    ],
}


class TestEducationClassification:
    def test_education_years_are_not_notice_period(self):
        assert classify_question("Start date year*", "start-year--0") == QuestionType.EDUCATION_START_YEAR
        assert classify_question("End date year*", "end-year--0") == QuestionType.EDUCATION_END_YEAR

    def test_job_start_questions_still_classify_as_notice_period(self):
        assert classify_question("What is your notice period?") == QuestionType.NOTICE_PERIOD
        assert classify_question("Desired start date") == QuestionType.NOTICE_PERIOD


class TestEducationResolution:
    def test_first_row_resolves_most_recent_degree(self):
        assert resolve_answer("School*", PROFILE, field_id="school--0").answer == "Santa Clara University"
        assert resolve_answer("End date year*", PROFILE, field_id="end-year--0").answer == "2019"
        assert resolve_answer("Start date year*", PROFILE, field_id="start-year--0").answer == "2017"

    def test_second_row_resolves_the_second_degree(self):
        assert resolve_answer("School*", PROFILE, field_id="school--1").answer == (
            "Pune Institute of Computer Technology"
        )
        assert resolve_answer("End date year*", PROFILE, field_id="end-year--1").answer == "2016"

    def test_row_beyond_the_profile_is_left_unanswered(self):
        # Inventing a third degree on a real application is worse than an empty
        # optional row, so an absent row must resolve to nothing.
        assert not resolve_answer("School*", PROFILE, field_id="school--2").answer

    def test_degree_maps_onto_the_options_the_form_offers(self):
        result = resolve_answer(
            "Degree*",
            PROFILE,
            options=["Bachelor's Degree", "Master's Degree", "Doctorate"],
            field_id="degree--0",
        )
        assert result.answer == "Master's Degree"

    def test_positional_lookup_requires_the_label_to_agree_with_the_id(self):
        # The row index only means something when the label really is the
        # education field its id claims; an unrelated question that happens to
        # carry that id must not be routed into the education block.
        assert _education_field("school--1", "How did you hear about us?") is None
        assert _education_field("school--1", "School*") == ("school", 1)

    def test_flat_profile_keys_still_answer_row_zero(self):
        flat = {"school": "Santa Clara University", "degree": "Master's Degree"}
        assert resolve_answer("School*", flat, field_id="school--0").answer == "Santa Clara University"
