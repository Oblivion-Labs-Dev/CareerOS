"""A country answer picks the country, not a territory that contains its name.

Cisco's and HPE's country lists put "United States Minor Outlying Islands"
before "United States of America", and both scored the same substring match.
"""

from __future__ import annotations

from app.services.application_assistant.profile_answer_resolver import _match_option, resolve_answer

COUNTRIES = [
    "Uganda", "Ukraine", "United Arab Emirates", "United Kingdom",
    "United States Minor Outlying Islands", "United States of America", "Uruguay",
]


def test_united_states_picks_the_usa_over_the_outlying_islands():
    assert _match_option(COUNTRIES, "United States") == "United States of America"


def test_resolver_answers_country_with_the_usa():
    profile = {"country": "United States"}
    assert resolve_answer("Country or Region\n*", profile, options=COUNTRIES).answer == "United States of America"


def test_abbreviated_usa_option_is_also_found():
    assert _match_option(["United States Minor Outlying Islands", "USA"], "United States") == "USA"
