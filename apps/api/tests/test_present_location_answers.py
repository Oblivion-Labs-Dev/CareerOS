"""Being willing to relocate is not living somewhere.

Rise8 asked "Are you located within a commutable distance into either: Colorado
Springs, CO / Aurora, CO / El Segundo, CA and are willing to be hybrid?" and was
answered "Yes" for a candidate in Auburn, WA. The place-commitment patterns that
should have caught it held literal backspace bytes instead of ``\\b``.
"""

from __future__ import annotations

import pathlib

import pytest

from app.services.application_assistant.profile_answer_resolver import resolve_answer

PROFILE = {"city": "Auburn", "state": "Washington", "location": "Auburn, WA", "relocate": "Yes"}
APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "app"


def test_located_near_another_state_is_no_even_when_willing_to_relocate():
    q = ("Are you located within a commutable distance into either: -Colorado Springs, CO "
         "-Aurora, CO -El Segundo, CA and are willing to be hybrid onsite (2-3x per week)?")
    assert resolve_answer(q, PROFILE, options=["Yes", "No"]).answer == "No"


def test_an_or_relocate_alternative_is_answered_from_the_relocation_stance():
    q = "I live within commutable distance of or am willing to relocate to the location where this position is based."
    assert resolve_answer(q, PROFILE, options=["Yes", "No"]).answer == "Yes"


@pytest.mark.parametrize("question", [
    "Do you live within commuting distance of Seattle, WA and can work hybrid?",
])
def test_a_place_in_the_candidates_own_state_is_not_answered_no(question):
    assert resolve_answer(question, PROFILE, options=["Yes", "No"]).answer != "No"


def test_a_lowercase_or_is_not_oregon():
    from app.services.application_assistant.profile_answer_resolver import _present_location_answer

    q = "Do you reside in the United States, Canada, or Mexico?"
    assert _present_location_answer(q, PROFILE) is None


def test_no_source_file_contains_a_literal_backspace():
    offenders = [str(p) for p in APP_ROOT.rglob("*.py") if b"\x08" in p.read_bytes()]
    assert not offenders, f"literal backspace (meant as \\b) in: {offenders}"
