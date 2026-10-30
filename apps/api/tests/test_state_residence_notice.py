"""State-law notices that ask the candidate to say whether they live in that state.

FanDuel's Greenhouse form carries the Massachusetts lie-detector notice with two
options: "I reside in Massachusetts and acknowledge ..." / "I don't reside in
Massachusetts." No rule matched it, the required field stayed blank and the
application was staged for review (2026-10-30). The profile's state answers it.
"""

from app.services.application_assistant.profile_answer_resolver import resolve_answer

NOTICE = (
    "It is unlawful in Massachusetts to require or administer a lie detector test as a "
    "condition of employment or continued employment. An employer who violates this law "
    "shall be subject to criminal penalties and civil liability."
)
OPTIONS = [
    "I reside in Massachusetts and acknowledge that I have received notice of this statement "
    "pursuant to G.L. c. 149, § 19B.",
    "I don’t reside in Massachusetts.",
]


def test_non_resident_picks_the_does_not_reside_option():
    res = resolve_answer(NOTICE, {"state": "Washington", "country": "United States"}, options=OPTIONS)
    assert res.answer == "I don’t reside in Massachusetts."


def test_resident_picks_the_acknowledgement():
    res = resolve_answer(NOTICE, {"state": "Massachusetts", "country": "United States"}, options=OPTIONS)
    assert res.answer == OPTIONS[0]


def test_unknown_state_is_left_for_review():
    res = resolve_answer(NOTICE, {}, options=OPTIONS)
    assert res.answer is None
