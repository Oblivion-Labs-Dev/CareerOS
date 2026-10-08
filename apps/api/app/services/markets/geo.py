"""Does a job location fall inside a market?

Locations arrive in every shape the boards use: "Seattle, WA", "Seattle,
Washington, USA", "US-WA-Redmond", "Redmond, WA, US | US", "Bellevue, Washington
| New York, NY". A posting is in the market when any one of its locations names
a market area (or the region itself). Ambiguous city names need the state too,
so "Kent, United Kingdom" and "Bellevue, NE" stay out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.markets.config import Market

_ZONE_ORDER = {"A": 0, "B": 1, "C": 2, "P": 3}
_SPLIT = re.compile(r"\s*(?:\||;|\n|\bor\b|\band\b)\s*", re.I)
_REMOTE = re.compile(r"\b(remote|virtual|work from home|wfh|telecommute)\b", re.I)
_DC = re.compile(r"\bwashington,?\s*d\.?c\.?\b|\bdistrict of columbia\b", re.I)


@dataclass
class LocationMatch:
    in_market: bool = False
    areas: list[str] = field(default_factory=list)
    zone: str | None = None
    remote: bool = False

    def to_dict(self) -> dict[str, object]:
        return {"inMarket": self.in_market, "areas": self.areas, "zone": self.zone, "remote": self.remote}


_PATTERN_CACHE: dict[str, tuple[re.Pattern[str], list[tuple[str, str, bool, re.Pattern[str]]]]] = {}


def _patterns(market: Market) -> tuple[re.Pattern[str], list[tuple[str, str, bool, re.Pattern[str]]]]:
    cached = _PATTERN_CACHE.get(market.id)
    if cached is not None:
        return cached
    built = _build_patterns(market)
    _PATTERN_CACHE[market.id] = built
    return built


def _build_patterns(market: Market) -> tuple[re.Pattern[str], list[tuple[str, str, bool, re.Pattern[str]]]]:
    state_bits = [re.escape(market.state_name.lower())] if market.state_name else []
    if market.state_code:
        state_bits.append(rf"{re.escape(market.state_code.lower())}")
    state = re.compile(rf"\b(?:{'|'.join(state_bits)})\b", re.I) if state_bits else re.compile(r"(?!)")
    areas = []
    for area in market.areas:
        names = [area.name.lower(), *area.aliases]
        pattern = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b", re.I)
        areas.append((area.name, area.zone, area.ambiguous, pattern))
    return state, areas


def match_location(location: str, market: Market) -> LocationMatch:
    text = (location or "").strip()
    result = LocationMatch(remote=bool(_REMOTE.search(text)))
    if not text:
        return result
    state, areas = _patterns(market)
    lowered = text.lower()
    whole_names_state = bool(state.search(_DC.sub(" ", lowered)))
    for segment in [s for s in _SPLIT.split(lowered) if s and s.strip()]:
        cleaned = _DC.sub(" ", segment)
        segment_state = bool(state.search(cleaned))
        if any(alias in cleaned for alias in market.region_aliases):
            result.in_market = True
        for name, zone, ambiguous, pattern in areas:
            if not pattern.search(cleaned):
                continue
            # "Washington" is both the state and nothing else here, so an
            # ambiguous city is accepted when its own segment or the whole
            # string names the state.
            if ambiguous and not (segment_state or whole_names_state):
                continue
            result.in_market = True
            if name not in result.areas:
                result.areas.append(name)
            if result.zone is None or _ZONE_ORDER.get(zone, 9) < _ZONE_ORDER.get(result.zone, 9):
                result.zone = zone
    return result


def areas_from_text(text: str, market: Market) -> list[str]:
    """Market areas named in free text such as the seed's "Seattle/Bellevue area"."""
    _, areas = _patterns(market)
    return [name for name, _zone, _amb, pattern in areas if pattern.search(text or "")]
