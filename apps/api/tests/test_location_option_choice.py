"""Pick the candidate's actual home town from a location typeahead.

Two live failures drove this. Typing "Seattle" offered "South Seattle,
Washington" first and a substring match took it. Typing "Auburn" for a candidate
in Auburn, Washington offers Auburn, Alabama first, and a match on the city name
alone took that — putting the wrong state on a real application.
"""

from app.services.application_assistant.playwright_autopilot_executor import (
    _pick_location_option,
)

WA = {"city": "Auburn", "state": "Washington", "location": "Auburn, WA"}
SEATTLE = {"city": "Seattle", "state": "Washington", "location": "Seattle, WA"}


def test_state_breaks_the_tie_between_same_named_cities():
    options = [
        "Auburn, Alabama, United States",
        "Auburn, Washington, United States",
        "Auburn Hills, Michigan, United States",
    ]
    assert options[_pick_location_option(options, "Auburn, WA", WA)] == "Auburn, Washington, United States"


def test_a_longer_city_name_never_wins():
    options = ["South Seattle, Washington, United States", "Seattle, Washington, United States"]
    assert options[_pick_location_option(options, "Seattle, WA", SEATTLE)] == "Seattle, Washington, United States"


def test_exact_match_wins_outright():
    options = ["Auburn, Alabama, United States", "Auburn, WA"]
    assert options[_pick_location_option(options, "Auburn, WA", WA)] == "Auburn, WA"


def test_no_option_in_the_right_state_resolves_to_nothing():
    # Every remaining suggestion is a different place with the same name, so an
    # empty field that gets reviewed beats a confident wrong answer.
    options = ["Auburn, Alabama, United States", "Auburn Hills, Michigan, United States"]
    assert _pick_location_option(options, "Auburn, WA", WA) is None


def test_city_only_match_is_allowed_when_the_state_is_unknown():
    profile = {"city": "Auburn"}
    options = ["Auburn, Alabama, United States"]
    assert _pick_location_option(options, "Auburn", profile) == 0


def test_state_abbreviation_in_the_option_also_counts():
    options = ["Auburn, AL, United States", "Auburn, WA, United States"]
    assert options[_pick_location_option(options, "Auburn, WA", WA)] == "Auburn, WA, United States"


def test_blank_suggestions_are_ignored():
    options = ["", "Auburn, Washington, United States"]
    assert _pick_location_option(options, "Auburn, WA", WA) == 1
