"""One saved wording, two answers: the one the control can take wins.

"Are you open to travel if required?" is Yes/No on most boards and a set of
percentage bands on Guidepoint's; the saved "Yes" cannot be selected there.
"""

from app.services.application_assistant.profile_answer_resolver import resolve_answer

QUESTION = "Are you open to travel if required?"
PATTERN = r"^are\ you\ open\ to\ travel\ if\ required\?"
PROFILE = {
    "screeningAnswers": [
        {"id": "travel_yes", "question": QUESTION, "answer": "Yes", "matchPatterns": [PATTERN]},
        {"id": "travel_band", "question": QUESTION, "answer": "50%+", "matchPatterns": [PATTERN]},
    ]
}
BANDS = ["No Travel", "0-25%", "25-50%", "50%+"]


def test_yes_no_control_takes_the_first_saved_answer():
    assert resolve_answer(QUESTION, PROFILE, options=["Yes", "No"]).answer == "Yes"


def test_band_control_takes_the_answer_that_names_an_option():
    res = resolve_answer(QUESTION, PROFILE, options=BANDS)
    assert res.answer == "50%+"
    assert res.profile_key == "screeningAnswers.travel_band"


def test_free_text_takes_the_first_saved_answer():
    assert resolve_answer(QUESTION, PROFILE).answer == "Yes"


NEROS_LABEL = (
    "Export Compliance: The person hired will have access to information and items controlled by the "
    "International Traffic in Arms Regulation (ITAR). To conform to U.S. Government space technology export "
    "regulations, applicant must be a U.S. Person*"
)
NEROS_OPTIONS = [
    'I am currently a "U.S. Person"',
    'I will soon become a "U.S. Person" (requires explanation if selected)',
    'I am not a "U.S. Person," but I am eligible for licensing (requires explanation if selected)',
]


def test_export_control_never_answers_with_a_value_the_control_lacks():
    res = resolve_answer(NEROS_LABEL, {"workAuth": {"usCitizen": False}}, options=NEROS_OPTIONS)
    assert res.answer is None


def test_export_control_takes_a_saved_statement_that_names_an_option():
    profile = {
        "workAuth": {"usCitizen": False},
        "screeningAnswers": [
            {"id": "itar_text", "question": "ITAR", "matchPatterns": [r"international\ traffic\ in\ arms"],
             "answer": "No, I am not a U.S. Person, but I am eligible to obtain an export license"},
            {"id": "itar_option", "question": "ITAR option", "matchPatterns": [r"international\ traffic\ in\ arms"],
             "answer": NEROS_OPTIONS[2]},
        ],
    }
    assert resolve_answer(NEROS_LABEL, profile, options=NEROS_OPTIONS).answer == NEROS_OPTIONS[2]


def test_no_saved_answer_names_an_option_so_none_is_invented():
    profile = {"screeningAnswers": PROFILE["screeningAnswers"][:1]}
    assert resolve_answer(QUESTION, profile, options=BANDS).answer not in BANDS[1:]
