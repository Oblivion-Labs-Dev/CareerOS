"""Option matching must ignore whitespace around slash separators.

Ashby renders pronoun choices spaced out ("He / Him / His") while the profile
stores them tight ("He/him/his"). Before this was handled the two never
compared equal, so the resolver emitted the raw profile string, no radio
matched it, and the required field was submitted empty — Ramp rejected the
application with "Missing entry for required field: What are your pronouns?".
"""

from app.services.application_assistant.ats_plugin_reference import (
    pick_best_matching_option,
    score_select_option_match,
)
from app.services.application_assistant.profile_answer_resolver import (
    _find_decline_option,
    _match_option,
)

PRONOUN_OPTIONS = [
    "She / Her / Hers",
    "He / Him / His",
    "They / Them / Theirs",
    "Ze / Hir / Hirs",
    "Prefer not to say / Skip",
    "Other",
]


class TestSeparatorSpacing:
    def test_tight_profile_value_matches_spaced_option(self):
        assert _match_option(PRONOUN_OPTIONS, "He/him/his") == "He / Him / His"

    def test_spaced_value_still_matches(self):
        assert _match_option(PRONOUN_OPTIONS, "He / Him / His") == "He / Him / His"

    def test_partial_pronoun_matches(self):
        assert _match_option(PRONOUN_OPTIONS, "he/him") == "He / Him / His"

    def test_does_not_cross_contaminate_other_pronouns(self):
        """'she/her' must never resolve to the He option, and vice versa."""
        assert _match_option(PRONOUN_OPTIONS, "she/her") == "She / Her / Hers"
        assert _match_option(PRONOUN_OPTIONS, "they/them") == "They / Them / Theirs"

    def test_decline_option_still_found(self):
        assert _find_decline_option(PRONOUN_OPTIONS) == "Prefer not to say / Skip"

    def test_pipe_separator_also_normalized(self):
        assert _match_option(["Remote | Hybrid"], "Remote|Hybrid") == "Remote | Hybrid"


class TestNoRegressionOnOrdinaryOptions:
    def test_yes_no_unaffected(self):
        assert _match_option(["Yes", "No"], "Yes") == "Yes"
        assert _match_option(["Yes", "No"], "Maybe") is None

    def test_race_options_unaffected(self):
        opts = ["Asian", "White", "Two or More Races", "Decline To Self Identify"]
        assert _match_option(opts, "Asian") == "Asian"
        assert _match_option(opts, "Decline To Self Identify") == "Decline To Self Identify"

    def test_unrelated_value_still_returns_none(self):
        assert pick_best_matching_option(PRONOUN_OPTIONS, "zzzz") is None

    def test_exact_match_still_scores_highest(self):
        assert score_select_option_match("Asian", "Asian") == 100
