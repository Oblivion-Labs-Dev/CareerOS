"""Contact and identity fields always come from the profile itself.

Cisco's "Email Address" matched a saved "Address 1" answer through its bare
"address" wording and was filled with the street address.
"""

from __future__ import annotations

import pytest

from app.services.application_assistant.profile_answer_resolver import resolve_answer

PROFILE = {
    "firstName": "Akshay",
    "lastName": "Borse",
    "email": "candidate@example.com",
    "phone": "(425) 555-0100",
    "screeningAnswers": [
        {"id": "addr", "question": "Address 1", "answer": "13310 306th St",
         "matchPatterns": [r"address\ 1", "address"]},
        {"id": "name", "question": "Legal name", "answer": "Wrong Person",
         "matchPatterns": ["name"]},
    ],
}


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Email Address\n*", "candidate+career@example.com"),
        ("Email address", "candidate+career@example.com"),
        ("Legal First Name\n*", "Akshay"),
    ],
)
def test_saved_answers_never_fill_identity_fields(question, expected):
    assert resolve_answer(question, PROFILE).answer == expected


def test_saved_address_still_answers_the_address_question():
    assert resolve_answer("Address 1", PROFILE).answer == "13310 306th St"
