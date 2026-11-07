"""Anyone can score jobs against their own resume profile, not only the bundled one."""

import json

import pytest

from app.services.application_assistant import profile_match


@pytest.fixture
def fresh_profile_cache():
    profile_match.default_profile.cache_clear()
    yield
    profile_match.default_profile.cache_clear()


def _write_profile(path, family_fit):
    path.write_text(json.dumps({
        "family_fit": family_fit,
        "seniority_fit": {str(i): 1.0 for i in range(6)},
        "skills": {}, "domains": {},
        "penalties": {"years_over": 99, "years_penalty": 0, "clearance_re": "top secret",
                      "clearance_penalty": 0, "cap": 15, "years_cap": 99, "language_re": ""},
    }), encoding="utf-8")


def test_env_var_points_matching_at_the_users_profile(tmp_path, monkeypatch, fresh_profile_cache):
    path = tmp_path / "pm_profile.json"
    _write_profile(path, {"product": 1.0, "backend": 0.1, "": 0.5})
    monkeypatch.setenv(profile_match.PROFILE_ENV, str(path))
    pm = profile_match.profile_components("Senior Product Manager", "")
    swe = profile_match.profile_components("Senior Backend Engineer", "")
    assert pm["score"] > swe["score"]


def test_a_missing_profile_file_fails_loudly(tmp_path, monkeypatch, fresh_profile_cache):
    monkeypatch.setenv(profile_match.PROFILE_ENV, str(tmp_path / "nope.json"))
    with pytest.raises(FileNotFoundError, match=profile_match.PROFILE_ENV):
        profile_match.default_profile()
