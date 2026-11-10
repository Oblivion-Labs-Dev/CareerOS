"""Regression: "Are you within 120 miles of our <offices>? which one?" with a None option.

Seen live on Greenhouse (FanDuel, 2026-11-05): the question classified as CITY
and answered "Auburn", which is not one of the six options, so the required
field stayed empty and the submit was rejected.
"""
from app.services.application_assistant.profile_answer_resolver import resolve_answer

Q = ("Are you located within 120 miles of the New York, Atlanta, Jersey City, Toronto "
     "or Los Angeles office? If so, which location?")
OPTS = ["New York", "Jersey City", "Atlanta", "Los Angeles", "Toronto", "None"]


def _ask(profile, opts=OPTS):
    return resolve_answer(question_text=Q, profile=profile, options=opts).answer


def test_far_away_candidate_answers_none():
    assert _ask({"location": "Auburn, WA", "city": "Auburn", "state": "Washington"}) == "None"


def test_candidate_in_an_office_city_picks_it():
    assert _ask({"location": "Atlanta, GA", "city": "Atlanta", "state": "Georgia"}) == "Atlanta"


def test_nearby_state_is_not_answered_none():
    # A New Jersey suburb may well be within range of New York: never guess "None".
    assert _ask({"location": "Princeton, NJ", "city": "Princeton", "state": "NJ"}) != "None"


def test_unknown_office_is_left_alone():
    opts = ["Boise", "None"]
    assert _ask({"location": "Auburn, WA", "city": "Auburn", "state": "Washington"}, opts) != "None"
