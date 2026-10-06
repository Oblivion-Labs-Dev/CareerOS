"""Classifier regressions found by running real applications.

Both of these sent otherwise-complete applications to review, and neither was
visible from the error text - the question simply arrived at a resolver that had
nothing to say about it.
"""

from __future__ import annotations

import pytest

from app.services.application_assistant.question_classifier import QuestionType, classify_question


def _t(question: str) -> QuestionType:
    return classify_question(question)


@pytest.mark.parametrize(
    "question",
    [
        # Lyft. "business unit of Lyft" matched a bare word-boundary test on
        # "unit" in the ADDRESS_LINE_2 patterns, so an employment-history
        # question was routed to the address resolver.
        "Have you been employed by Lyft, or any subsidiary, affiliate, or business "
        "unit of Lyft, in the past (whether on a full-time or part-time basis)?",
        # Brex. The compound phrasing with commas between the adverb and the
        # verb fell through every pattern and reached UNKNOWN.
        "Do you currently, or have you previously, worked at Capital One or a "
        "company acquired by Capital One as an employee, contractor or intern?",
        "Have you previously worked at Amazon?",
        "Have you ever been employed by Twitch?",
        "Are you a former employee of this company?",
    ],
)
def test_employment_history_questions_classify_as_company_history(question):
    assert _t(question) == QuestionType.COMPANY_HISTORY


@pytest.mark.parametrize(
    "question",
    [
        "Address Line 2",
        "Street Address 2",
        "Apt, Suite, etc.",
        "Apartment or suite number",
        "Unit #",
        "Street address line 2 (apt, suite)",
        "Suite",
    ],
)
def test_real_address_line_2_labels_still_classify(question):
    """The narrowed patterns must not lose genuine address fields."""
    assert _t(question) == QuestionType.ADDRESS_LINE_2


def test_plain_street_address_is_not_line_2():
    assert _t("Street Address") == QuestionType.ADDRESS


def test_unit_in_a_non_address_sentence_is_not_an_address():
    """The specific shape of the Lyft bug, stated directly."""
    assert _t("Which business unit would you join?") != QuestionType.ADDRESS_LINE_2
    assert _t("Have you worked for any business unit of Stripe?") == QuestionType.COMPANY_HISTORY


def test_previously_applied_is_not_treated_as_employment():
    """'Applied to' is not employment history.

    The profile records no application history, so there is no honest answer -
    this must not be quietly answered as though it were a "did you work here"
    question.
    """
    assert _t("Have you previously applied to Amazon or any Amazon subsidiary?") != QuestionType.COMPANY_HISTORY


# The fixes below came from bucketing ~1,200 live NEEDS_REVIEW/STAGED jobs by
# their "DOM Verification mismatch: Required field '<X>' is empty" reason:
# each of these labels was resolved to the wrong QuestionType (or none at
# all), so the field was either filled with an answer that could never match
# whatever control the field really was, or never attempted.


def test_academic_self_rating_is_not_a_school_name_request():
    """"...at high school" contains "school" but wants a subjective rating.

    No resolver can answer this honestly without fabricating a claim, so it
    must fall to UNKNOWN (the normal LLM/manual-review path) rather than be
    answered with the candidate's actual school name.
    """
    assert _t("How did you perform in mathematics at high school?") == QuestionType.UNKNOWN
    assert _t("How did you perform in your native language at high school?") == QuestionType.UNKNOWN


def test_name_entry_attestation_is_not_a_name_request():
    """"Have you added your...name" asks whether a field was filled in correctly."""
    assert (
        _t("Have you added your full legal name and surname (including any middle names)?")
        == QuestionType.ACCURACY_CONFIRMATION
    )


@pytest.mark.parametrize(
    "question",
    [
        "Are you authorized to lawfully work in the country where this role is located?",
        "Are you legally authorized to work in the country where this role is based?",
    ],
)
def test_work_authorization_with_adverb_is_not_country(question):
    """An adverb between "to" and "work" must not fall through to COUNTRY."""
    assert _t(question) == QuestionType.WORK_AUTHORIZED


def test_where_are_you_based_is_location_not_unknown():
    assert _t("Where are you currently based?") == QuestionType.LOCATION


def test_highest_level_of_completed_education_is_degree():
    assert _t("What is your highest level of completed education?") == QuestionType.DEGREE


def test_available_to_begin_work_is_notice_period():
    assert _t("When are you available to begin work at Encora?") == QuestionType.NOTICE_PERIOD


@pytest.mark.parametrize(
    "question",
    [
        "Please email me about future job openings",
        "Email me about other job openings within the Booking Holdings entities and recruitment-related communications",
    ],
)
def test_marketing_opt_in_is_not_an_email_address_request(question):
    """A checkbox to opt into marketing email is not a request for the candidate's address."""
    assert _t(question) == QuestionType.MARKETING_CONSENT


@pytest.mark.parametrize(
    "question",
    [
        # Scale AI's phrasing. Neither writes "government employee" adjacently,
        # so both fell through to UNKNOWN and were answered "NA" -- a non-answer
        # on a compliance question whose factual answer is "No".
        "Are you a current or former civilian or military employee of the United States"
        " Government? (If yes, when/where were you last employed and what was your"
        " highest grade/rank and title?)",
        "Do you have any restrictions on post-government employment?"
        " (If yes, please describe.)",
        "Have you been involved in procurement or contract award activities as a"
        " government employee?",
    ],
)
def test_government_employment_questions_are_conflict_checks(question):
    assert _t(question) == QuestionType.GOVERNMENT_CONFLICT


@pytest.mark.parametrize(
    "question",
    [
        "Are you legally authorized to work in the United States?",
        "Will you now or in the future require sponsorship for employment visa status?",
    ],
)
def test_widened_government_patterns_do_not_swallow_work_authorization(question):
    """The government-conflict patterns mention "United States" and "employment",
    which the work-authorization and sponsorship questions also do."""
    assert _t(question) != QuestionType.GOVERNMENT_CONFLICT


@pytest.mark.parametrize(
    "question",
    [
        "Did someone from Fleetio refer you? If so, share their name below. If not, list 'N/A'.",
        "Did a current Praxenter refer you?",
    ],
)
def test_referral_variants_classify_as_referral(question):
    assert _t(question) == QuestionType.REFERRAL


@pytest.mark.parametrize(
    "question",
    [
        "Are you an existing employee at Life360, Tile, or Jiobit?",
        "Have you previously worked within the Motional ecosphere?",
    ],
)
def test_company_history_variants_classify_correctly(question):
    assert _t(question) == QuestionType.COMPANY_HISTORY


def test_lgbtq_community_is_sexual_orientation():
    assert _t("Do you identify as a member of the LGBT2QIA+ community?") == QuestionType.SEXUAL_ORIENTATION


def test_interview_problem_acknowledgment():
    assert (
        _t(
            "If selected for a preliminary interview, you may be asked to work through a Python coding problem. "
            "Do you acknowledge this?"
        )
        == QuestionType.ACCURACY_CONFIRMATION
    )


def test_approved_payroll_states_location_confirmation():
    q = (
        "Without requiring relocation, can you confirm that you are based in one of the following Grove approved "
        "payroll states? (Arizona, California, Colorado, Connecticut, Florida, Georgia, Illinois, Indiana, Kentucky, "
        "Maine, Maryland, Massachusetts, Michigan, Minnesota, Nevada, New Jersey, New Mexico, New York, "
        "North Carolina, Ohio, Oregon, Pennsylvania, South Carolina, Tennessee, Texas, Utah, Virginia, Washington, Wisconsin)"
    )
    assert _t(q) == QuestionType.LOCATION_CONFIRMATION


@pytest.mark.parametrize(
    "question",
    [
        "Please explain any gaps in your work history. If none, please say N/A. *",
        "Explain any gaps in your employment history",
        "Do you have any employment gaps?",
    ],
)
def test_employment_gap_questions_classify_and_resolve(question):
    assert _t(question) == QuestionType.EMPLOYMENT_GAP
    from app.services.application_assistant.profile_answer_resolver import resolve_answer
    res = resolve_answer(question, {}, [])
    assert res.answer == "N/A"


def test_salary_information_acknowledgment():
    q = "I confirm that I have read and acknowledged Code for America's posted salary information for this position.*"
    assert _t(q) == QuestionType.ACCURACY_CONFIRMATION


def test_talkspace_text_messaging_consent():
    q = "Talkspace uses text messaging to help move you through the interview process quickly. We text to share application updates, schedule interviews, and be more available to support you during the process. *"
    assert _t(q) == QuestionType.SMS_CONSENT


def test_defense_unicorns_ccpa_disclosure():
    q = "In this question description we have provided a link to our California Consumer Privacy Act (CCPA) disclosure. Please acknowledge that you have been provided with this disclosure - Link included in question description.*"
    assert _t(q) == QuestionType.PRIVACY_CONSENT


def test_defense_unicorns_conference_attendance():
    q = "Did you meet with or see Defense Unicorns while attending an event or conference (e.g. Kubecon)?*"
    assert _t(q) == QuestionType.COMPANY_FAMILIARITY
    from app.services.application_assistant.profile_answer_resolver import resolve_answer
    res = resolve_answer(q, {}, ["Yes", "No"])
    assert res.answer == "No"


def test_care_access_outside_employment():
    q = "If hired by Care Access, do you intend to maintain any outside employment, consulting, contract work, self-employment, or other work activity?*"
    assert _t(q) == QuestionType.GOVERNMENT_CONFLICT
    from app.services.application_assistant.profile_answer_resolver import resolve_answer
    res = resolve_answer(q, {}, ["Yes", "No"])
    assert res.answer == "No"


def test_runzero_primary_coding_language():
    q = "What is your primary coding language? *"
    assert _t(q) == QuestionType.PREFERRED_LANGUAGE
    from app.services.application_assistant.profile_answer_resolver import resolve_answer
    res = resolve_answer(q, {}, [])
    assert res.answer == "Python"




def test_netdocuments_previously_been_an_employee():
    q = "Have you previously been an employee of NetDocuments?*"
    assert _t(q) == QuestionType.COMPANY_HISTORY
    from app.services.application_assistant.profile_answer_resolver import resolve_answer
    res = resolve_answer(q, {}, ["Yes", "No"])
    assert res.answer == "No"


def test_smartasset_live_within_united_states_requirement():
    q = ("SmartAsset is only able to employ individuals who live within the United States. "
         "Are you able to meet this requirement?*")
    assert _t(q) == QuestionType.LOCATION_CONFIRMATION
    from app.services.application_assistant.profile_answer_resolver import resolve_answer
    res = resolve_answer(q, {}, ["Yes", "No"])
    assert res.answer == "Yes"
