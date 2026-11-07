"""Whose taste orders the application queue.

The ranker was tuned by hand for one person: AI/ML engineering first, a fixed
engineering role order (Senior, Forward Deployed, Principal, SDE 2, Staff,
SDE 1), the taste markers in docs/job-preferences.md, and Washington State over
the rest of the US. Applied to a product manager in Austin, that ordering is
simply wrong, so it is now the opt-in ``"owner"`` preset.

The default (``"neutral"``) orders by recency, the user's preferred locations
and the match score against their own resume, and works for any role.

The file is ``apps/api/config/ranking_preferences.json``, or the path in
``CAREEROS_RANKING_PREFERENCES``::

    {"preset": "neutral", "preferred_locations": ["Austin", "TX", "Remote"]}

A missing file means the neutral defaults. A file that exists but cannot be
read raises: a typo must not silently reorder somebody's job search.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PRESETS = ("neutral", "owner")
DEFAULT_PATH = Path(__file__).resolve().parents[3] / "config" / "ranking_preferences.json"


@dataclass(frozen=True)
class RankingPreferences:
    preset: str = "neutral"
    preferred_locations: tuple[str, ...] = ()

    @property
    def owner_taste(self) -> bool:
        return self.preset == "owner"


def preferences_path() -> Path:
    raw = (os.environ.get("CAREEROS_RANKING_PREFERENCES") or "").strip()
    return Path(raw) if raw else DEFAULT_PATH


@lru_cache(maxsize=1)
def _load(path_str: str) -> RankingPreferences:
    path = Path(path_str)
    if not path.exists():
        return RankingPreferences()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Unreadable ranking preferences file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Ranking preferences file {path} must hold a JSON object")
    preset = str(data.get("preset") or "neutral").strip().lower()
    if preset not in PRESETS:
        raise ValueError(f"Unknown ranking preset {preset!r} in {path}; expected one of {PRESETS}")
    locations = data.get("preferred_locations") or []
    if not isinstance(locations, list) or not all(isinstance(x, str) for x in locations):
        raise ValueError(f"preferred_locations in {path} must be a list of strings")
    cleaned = tuple(x.strip().lower() for x in locations if x.strip())
    return RankingPreferences(preset=preset, preferred_locations=cleaned)


def get_ranking_preferences() -> RankingPreferences:
    return _load(str(preferences_path()))


def clear_cache() -> None:
    _load.cache_clear()


_DC_LOCATION = re.compile(r"district of columbia|washington,?\s*d\.?c\b")


def matches_preferred_location(location: str, preferred: tuple[str, ...]) -> bool:
    """Whether a posting's location names one of the preferred places.

    Places match on letter boundaries, so "WA" does not match "Iowa" or
    "Ottawa", and "Washington" never matches Washington, D.C.
    """
    loc_l = (location or "").lower()
    if not loc_l or not preferred:
        return False
    for place in preferred:
        if not re.search(rf"(?<![a-z]){re.escape(place)}(?![a-z])", loc_l):
            continue
        if place in ("washington", "wa") and _DC_LOCATION.search(loc_l):
            continue
        return True
    return False
