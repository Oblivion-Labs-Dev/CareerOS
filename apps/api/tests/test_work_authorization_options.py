"""An H-1B holder's work-authorization answer is the option that says so.

Rvo Health offers "I am ONLY allowed to work for my current employer in the
U.S. and I will require sponsorship ...", which reads as neither a "yes" nor
"authorized", so the required question was left blank and staged for review.
"""

from __future__ import annotations

from app.services.application_assistant.profile_answer_resolver import resolve_answer

RVO = [
    "I am authorized to work without sponsorship or restrictions for any employer in the U.S.",
    "I am ONLY allowed to work for my current employer in the U.S. and I will require "
    "sponsorship now or in the future to work in the US",
    "My status to work in the U.S. is unknown",
]


def _profile(requires: bool) -> dict:
    return {"workAuth": {
        "authorizedToWorkInUS": True,
        "requiresSponsorshipNowOrFuture": requires,
        "authorizationType": "H-1B" if requires else "",
    }}


def test_h1b_holder_picks_the_employer_bound_option():
    assert resolve_answer("Work Authorization", _profile(True), options=RVO).answer == RVO[1]


def test_candidate_without_sponsorship_needs_picks_unrestricted():
    assert resolve_answer("Work Authorization", _profile(False), options=RVO).answer == RVO[0]


def test_options_denying_authorization_are_never_picked():
    options = [
        "I am not authorized to work in the U.S. and will require sponsorship",
        "My visa status is unknown",
    ]
    assert resolve_answer("Work Authorization", _profile(True), options=options).answer not in options
