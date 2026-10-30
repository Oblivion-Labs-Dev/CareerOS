"""A state dropdown that lists two-letter codes is answered with the code.

A "What state do you currently live in?" offers AL, AK, ... WA. The
profile stores "Washington", which matched no option, so the resolver returned
the full name and the form filler picked "HI" ("wasHIngton") - submitted
2026-10-30. The profile's state is mapped to its USPS code when only codes are
offered, and the other way round.
"""

from app.services.application_assistant.profile_answer_resolver import resolve_answer

CODES = ["AL", "AK", "AZ", "CA", "GU", "HI", "NY", "OR", "TX", "WA", "WV", "BC"]


def test_full_state_name_maps_to_its_code():
    res = resolve_answer("What state do you currently live in?", {"state": "Washington"}, options=CODES)
    assert res.answer == "WA"


def test_code_maps_to_full_name_option():
    opts = ["Hawaii", "Washington", "West Virginia"]
    res = resolve_answer("What state do you currently live in?", {"state": "WA"}, options=opts)
    assert res.answer == "Washington"


def test_unmatched_state_does_not_return_an_unofferred_value():
    res = resolve_answer("What state do you currently live in?", {"state": "Washington"}, options=["AL", "AK", "HI"])
    assert res.answer != "HI"
    assert res.answer is None
