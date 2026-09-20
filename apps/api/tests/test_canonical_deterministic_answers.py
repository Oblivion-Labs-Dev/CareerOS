"""Deterministic answers for the questions Canonical's form actually asks.

Three separate defects, all found by reading the stored failures on 51 live
Canonical applications rather than by guessing at the form:

1. The originality declaration matched no pattern at all (43 jobs blocked).
2. "What time zone are you in?" was classified as TIMEZONE_AVAILABILITY, whose
   resolver answers "Yes" — right for "can you work Eastern hours?", a
   non-answer here, so the field stayed empty.
3. "…since you graduated your first undergraduate degree, how many companies
   have you worked for?" was intercepted by the bare `degree` pattern and would
   have answered an employer count with a qualification level.
"""

from __future__ import annotations

import pytest

from app.services.application_assistant.profile_answer_resolver import (
    AnswerResolution,
    _resolve_employer_count,
    _resolve_originality_declaration,
    _resolve_timezone_location,
    candidate_timezone,
)
from app.services.application_assistant.question_classifier import (
    QuestionType,
    classify_question,
)

DECLARATION = (
    "During this application process I agree to use only my own words. I understand "
    "that plagiarism, the use of AI or other generated content will disqualify my "
    "application.*"
)


def _type(label: str) -> QuestionType:
    result = classify_question(label)
    return getattr(result, "question_type", result)


def _res() -> AnswerResolution:
    return AnswerResolution()


# ── Classification ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        (DECLARATION, QuestionType.ORIGINALITY_DECLARATION),
        ("What time zone are you in?*", QuestionType.TIMEZONE_LOCATION),
        ("Which time zone are you in?", QuestionType.TIMEZONE_LOCATION),
        (
            "In the past ten years, looking only at the time since you graduated your "
            "first undergraduate degree, how many companies have you worked for?",
            QuestionType.EMPLOYER_COUNT,
        ),
    ],
)
def test_canonical_questions_are_recognised(label, expected):
    assert _type(label) == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        # The new patterns must not swallow the questions they sit in front of.
        ("Are you comfortable working Eastern Time hours?", QuestionType.TIMEZONE_AVAILABILITY),
        ("Can you overlap with our core hours?", QuestionType.TIMEZONE_AVAILABILITY),
        ("What is your highest level of education?", QuestionType.DEGREE),
        ("What degree did you earn?", QuestionType.DEGREE),
    ],
)
def test_neighbouring_question_types_are_untouched(label, expected):
    assert _type(label) == expected


def test_a_fact_the_profile_cannot_hold_stays_unclassified():
    """Canonical asks about high-school mathematics. Nothing should claim it."""
    assert _type("How did you perform in mathematics at high school?*") == QuestionType.UNKNOWN


# ── Cross-company blockers found by surveying every review job ───────────────


@pytest.mark.parametrize(
    "label",
    [
        # British spelling. The patterns were American-only, so this fell to the
        # bare COUNTRY pattern and a yes/no work-authorisation question would
        # have been answered with a country name. That answer has to be exactly
        # right: the candidate requires sponsorship.
        "Are you authorised to work in the country in which this role is located?",
        "Are you authorized to work in the United States?",
        "Do you have the right to work in the UK?",
    ],
)
def test_work_authorisation_is_recognised_in_both_spellings(label):
    assert _type(label) == QuestionType.WORK_AUTHORIZED


def test_a_plain_country_question_is_still_a_country_question():
    assert _type("What country do you live in?") == QuestionType.COUNTRY


@pytest.mark.parametrize(
    "label",
    [
        # Asana: a parenthetical between "employed" and "by" broke the
        # contiguous pattern - the same shape as the work-authorisation adverb.
        "Have you been employed, or otherwise engaged, by an Asana entity in the past?",
        # Booking Holdings: "presently", not "currently".
        "Are you presently employed by any company within the Booking Holdings group?",
        # Agoda: "personal relationship", with no "familial" for the existing
        # pattern to key on.
        "Do you as a candidate have a personal relationship with a current Agoda employee?",
    ],
)
def test_prior_employment_and_relationship_questions_are_recognised(label):
    assert _type(label) == QuestionType.COMPANY_HISTORY


@pytest.mark.parametrize("label", [
    "What is your current organisation?",
    "What is your current organization?",
])
def test_current_employer_is_recognised_in_both_spellings(label):
    assert _type(label) == QuestionType.CURRENT_COMPANY


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        # Greenhouse renders the education block's month and year as two
        # separate required selects. Only the year half was classified, so the
        # month stayed empty and held the application.
        ("End date month*", QuestionType.EDUCATION_END_MONTH),
        ("End date year*", QuestionType.EDUCATION_END_YEAR),
        ("Start date month*", QuestionType.EDUCATION_START_MONTH),
        ("Start date year*", QuestionType.EDUCATION_START_YEAR),
    ],
)
def test_education_month_and_year_are_both_classified(label, expected):
    assert _type(label) == expected


def test_education_end_month_comes_from_the_recorded_date():
    from app.services.application_assistant.profile_answer_resolver import (
        _resolve_education_end_month,
    )

    res = _res()
    _resolve_education_end_month(res, {"education": [{"endDate": "06/2019"}]}, [])

    assert res.answer == "June"


def test_education_month_is_not_invented_when_unrecorded():
    from app.services.application_assistant.profile_answer_resolver import (
        _resolve_education_end_month,
    )

    res = _res()
    _resolve_education_end_month(res, {"education": [{"endDate": "2019"}]}, [])

    assert res.answer is None, "a bare year records no month; do not guess one"


# ── The originality declaration is never auto-answered ───────────────────────


def test_the_originality_declaration_is_affirmed_by_instruction():
    """Affirmed at the candidate's explicit direction.

    This resolver originally refused: the clause says AI-generated content
    disqualifies the application, and CareerOS drafts with a model. The
    candidate was shown that reasoning and overruled it, which is theirs to
    decide — they make the declaration and they carry it.

    Pinned as a test so the behaviour is a recorded decision rather than
    something that drifts back and forth.
    """
    res = _res()

    _resolve_originality_declaration(res, {"firstName": "A"}, ["I agree", "I disagree"])

    assert res.answer == "I agree"
    assert not res.blocking_errors


def test_the_declaration_falls_back_to_plain_text_when_there_are_no_options():
    res = _res()

    _resolve_originality_declaration(res, {}, [])

    assert res.answer == "I agree"


# ── Time zone: a zone, not a yes ─────────────────────────────────────────────


def test_timezone_is_derived_from_the_recorded_location():
    assert candidate_timezone({"state": "Washington"}) == (
        "America/Los_Angeles", "Pacific Time (PT)",
    )
    assert candidate_timezone({"location": "Auburn, WA"})[1] == "Pacific Time (PT)"
    assert candidate_timezone({"location": "Austin, TX"})[1] == "Central Time (CT)"


def test_an_explicit_profile_timezone_wins():
    assert candidate_timezone({"timezone": "Europe/London", "state": "Washington"}) == (
        "Europe/London", "Europe/London",
    )


def test_an_unresolvable_location_is_not_guessed():
    """An invented time zone on a submitted application is a false statement."""
    assert candidate_timezone({"location": "somewhere nice"}) is None
    assert candidate_timezone({}) is None


def test_the_question_gets_a_zone_rather_than_yes():
    res = _res()

    _resolve_timezone_location(res, {"location": "Auburn, WA", "state": "Washington"}, [])

    assert res.answer == "Pacific Time (PT)"
    assert res.answer != "Yes"
    assert not res.blocking_errors


def test_an_unresolvable_location_routes_to_review():
    res = _res()

    _resolve_timezone_location(res, {"location": ""}, [])

    assert res.answer is None
    assert res.blocking_errors


def test_options_that_cannot_express_the_zone_route_to_review():
    """Picking the nearest offered zone would state the wrong one."""
    res = _res()

    _resolve_timezone_location(res, {"state": "Washington"}, ["Europe/Berlin", "Asia/Tokyo"])

    assert res.answer is None
    assert res.blocking_errors


# ── Employer count comes from work history ───────────────────────────────────


def test_employers_are_counted_from_recorded_history():
    res = _res()
    profile = {"workExperience": [
        {"company": "Amazon"}, {"company": "Microsoft"}, {"company": "Amazon"},
    ]}

    _resolve_employer_count(res, profile, [])

    assert res.answer == "2", "the same employer twice is one employer"
    assert res.profile_key == "workExperience"


def test_an_empty_history_is_not_invented():
    res = _res()

    _resolve_employer_count(res, {"workExperience": []}, [])

    assert res.answer is None
    assert res.blocking_errors
