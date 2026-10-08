"""Extension points for growing a market beyond its seed list.

Only the contracts exist today. V1 companies come from the seed importer; a
later live source (H-1B LCA filings, a funding feed, a user's own list) plugs
in as a MarketDiscoveryProvider yielding CompanyCandidates, which a
CompanyResolver matches to existing registry records (or creates), after which
the CareerSourceDetector and the normal refresh take over unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.services.markets.config import Market
from app.services.markets.detector import Detection


@dataclass
class CompanyCandidate:
    """A company some provider believes belongs in a market, with why."""

    name: str
    provider: str
    career_url: str = ""
    areas: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


class MarketDiscoveryProvider(Protocol):
    id: str

    def discover(self, market: Market) -> AsyncIterator[CompanyCandidate]:
        """Yield candidate employers for ``market``."""
        ...


class CompanyResolver(Protocol):
    def resolve(self, candidate: CompanyCandidate) -> str | None:
        """The registry id this candidate refers to, or None when it is new."""
        ...


class CareerSourceDetector(Protocol):
    async def detect(self, client: httpx.AsyncClient, company: dict[str, Any]) -> Detection:
        """Where and how this company's jobs can be read."""
        ...
