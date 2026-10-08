"""Market definitions.

A market is data, not code: everything Seattle-specific lives in markets.json,
so a new metro is one more entry there (areas, state, seed file, provider
location hints) with no new scraper or code path.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).with_name("markets.json")
DEFAULT_SEED_DIR = Path(__file__).resolve().parents[3] / "data" / "markets" / "seeds"


@dataclass(frozen=True)
class MarketArea:
    name: str
    zone: str
    aliases: tuple[str, ...] = ()
    # A city name that also exists elsewhere ("Kent", "Bellevue", "Redmond")
    # only counts when the location also names the market's state.
    ambiguous: bool = False


@dataclass(frozen=True)
class MarketSeed:
    id: str
    type: str
    file: str
    sheet: str
    reference_sheet: str = ""
    h1b_source: str = ""


@dataclass(frozen=True)
class Market:
    id: str
    name: str
    tagline: str
    origin: str
    country: str
    state_code: str
    state_name: str
    anchor_location: str
    areas: tuple[MarketArea, ...]
    zones: tuple[dict[str, str], ...]
    region_aliases: tuple[str, ...]
    seeds: tuple[MarketSeed, ...]
    fresh_hours: float = 6.0
    detection_ttl_hours: float = 168.0
    provider_hints: dict[str, Any] = field(default_factory=dict)

    def area(self, name: str) -> MarketArea | None:
        key = name.strip().lower()
        return next((a for a in self.areas if a.name.lower() == key or key in a.aliases), None)

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tagline": self.tagline,
            "origin": self.origin,
            "state": self.state_code,
            "areas": [{"name": a.name, "zone": a.zone} for a in self.areas],
            "zones": list(self.zones),
        }


def _parse(entry: dict[str, Any]) -> Market:
    state = entry.get("state") or {}
    refresh = entry.get("refresh") or {}
    return Market(
        id=entry["id"],
        name=entry["name"],
        tagline=entry.get("tagline", ""),
        origin=entry.get("origin", ""),
        country=entry.get("country", "US"),
        state_code=str(state.get("code", "")).upper(),
        state_name=str(state.get("name", "")),
        anchor_location=entry.get("anchorLocation", ""),
        areas=tuple(
            MarketArea(
                name=a["name"],
                zone=a.get("zone", ""),
                aliases=tuple(x.lower() for x in a.get("aliases", [])),
                ambiguous=bool(a.get("ambiguous", False)),
            )
            for a in entry.get("areas", [])
        ),
        zones=tuple(entry.get("zones", [])),
        region_aliases=tuple(x.lower() for x in entry.get("regionAliases", [])),
        seeds=tuple(
            MarketSeed(
                id=s["id"],
                type=s.get("type", "xlsx"),
                file=s["file"],
                sheet=s.get("sheet", ""),
                reference_sheet=s.get("referenceSheet", ""),
                h1b_source=s.get("h1bSource", ""),
            )
            for s in entry.get("seeds", [])
        ),
        fresh_hours=float(refresh.get("freshHours", 6)),
        detection_ttl_hours=float(refresh.get("detectionTtlHours", 168)),
        provider_hints=dict(entry.get("providerHints") or {}),
    )


@lru_cache(maxsize=1)
def load_markets() -> dict[str, Market]:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {m["id"]: _parse(m) for m in raw.get("markets", [])}


def get_market(market_id: str) -> Market | None:
    return load_markets().get(market_id)


def seed_dir() -> Path:
    override = os.environ.get("CAREEROS_MARKET_SEED_DIR", "").strip()
    return Path(override) if override else DEFAULT_SEED_DIR


def resolve_seed_path(seed: MarketSeed) -> Path | None:
    """The seed file, from the seed directory or the user's Downloads folder."""
    for base in (seed_dir(), Path.home() / "Downloads"):
        candidate = base / seed.file
        if candidate.is_file():
            return candidate
    return None
