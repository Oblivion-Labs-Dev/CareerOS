"""A saved "Company careers page" answers every "How did you hear about…" form.

Each employer names its own careers page differently, so the saved text alone
selects nothing and left the field blank (Coinbase offers "Career Page").
"""

from __future__ import annotations

import pytest

from app.services.application_assistant.profile_answer_resolver import resolve_answer

WORDINGS = [
    "How did you hear about this job?",
    "How did you hear about us?",
    "How did you hear about this position?",
    "Where did you hear about us?",
]


def _profile() -> dict:
    return {
        "screeningAnswers": [{
            "id": "source",
            "question": WORDINGS[0],
            "answer": "Company careers page",
            "matchPatterns": [w.lower().replace("?", r"\?") for w in WORDINGS],
        }]
    }


@pytest.mark.parametrize(
    ("question", "options", "expected"),
    [
        ("How did you hear about this job?*", ["Career Page", "LinkedIn", "Job Board", "Other"], "Career Page"),
        ("How did you hear about us?", ["LinkedIn", "Company Website / Careers Page", "Other"],
         "Company Website / Careers Page"),
        ("How did you hear about us?", ["Company Site", "Google", "Indeed", "Other"], "Company Site"),
        ("How did you hear about this position?", ["I was Referred", "BeyondTrust Website", "Other"],
         "BeyondTrust Website"),
        ("How did you hear about this job?", ["Campus Career Site", "Samsara Careers Site", "Ad on Website"],
         "Samsara Careers Site"),
    ],
)
def test_careers_page_answer_selects_the_employers_own_option(question, options, expected):
    assert resolve_answer(question, _profile(), options=options).answer == expected


def test_two_career_sites_are_left_for_the_candidate():
    options = ["Enova Career Site", "Pangea Career Site", "LinkedIn", "Other"]
    answer = resolve_answer("How did you hear about this job?", _profile(), options=options).answer
    assert answer not in options
