"""The queue order must fit whoever runs CareerOS, not only its original author.

It used to rank every user as a senior AI engineer in Washington State: a
product manager's postings scored nothing for role and a Seattle posting beat
the user's own city. The author's order is now the opt-in "owner" preset.
"""

from datetime import datetime, timezone

import pytest

from app.services.application_assistant import ranking_preferences
from app.services.application_assistant.job_filter_ranker import queue_priority_score


@pytest.fixture
def prefs_file(tmp_path, monkeypatch):
    def write(text: str):
        path = tmp_path / "ranking_preferences.json"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setenv("CAREEROS_RANKING_PREFERENCES", str(path))
        ranking_preferences.clear_cache()

    yield write
    ranking_preferences.clear_cache()


def _job(title: str, location: str, score: float = 50.0) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {"title": title, "location": location, "matchScore": score, "datePosted": now}


def test_neutral_preset_does_not_favour_the_authors_role_or_state():
    pm = _job("Senior Product Manager", "Austin, TX", score=80)
    ai = _job("Senior AI Engineer", "Seattle, WA", score=40)
    assert queue_priority_score(pm) > queue_priority_score(ai)


def test_neutral_preset_prefers_the_users_own_locations(prefs_file):
    prefs_file('{"preferred_locations": ["Austin", "TX"]}')
    home = _job("Technical Program Manager", "Austin, TX", score=40)
    away = _job("Technical Program Manager", "Seattle, WA", score=80)
    assert queue_priority_score(home) > queue_priority_score(away)


def test_preferred_state_codes_match_on_letter_boundaries():
    m = ranking_preferences.matches_preferred_location
    assert m("Remote - WA", ("wa",))
    assert not m("Des Moines, Iowa", ("wa",))
    assert not m("Washington, DC", ("washington",))


def test_owner_preset_keeps_the_original_order(owner_ranking_preset):
    pm = _job("Senior Product Manager", "Austin, TX", score=80)
    ai = _job("Senior AI Engineer", "Seattle, WA", score=40)
    assert queue_priority_score(ai) > queue_priority_score(pm)


def test_a_broken_preferences_file_fails_loudly(prefs_file):
    prefs_file('{"preset": "ownr"}')
    with pytest.raises(ValueError, match="Unknown ranking preset"):
        queue_priority_score(_job("Engineer", "Austin, TX"))
