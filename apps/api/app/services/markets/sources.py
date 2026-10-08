"""Career source vocabulary: how a company's jobs can be read, and how well that is working.

Source type (how) and health (how well) are separate on purpose: a MANUAL
company is not broken, and a healthy ATS can still go FAILED tomorrow.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class SourceType(str, Enum):
    ATS_API = "ATS_API"
    PROPRIETARY_API = "PROPRIETARY_API"
    JSON_ENDPOINT = "JSON_ENDPOINT"
    STATIC_HTML = "STATIC_HTML"
    BROWSER = "BROWSER"
    MANUAL = "MANUAL"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class Health(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"


# Source types CareerOS can enumerate on its own.
AUTOMATIC_TYPES = {SourceType.ATS_API, SourceType.PROPRIETARY_API, SourceType.JSON_ENDPOINT, SourceType.STATIC_HTML}


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    source_type: SourceType
    # Refresh order: cheap public JSON first, paginated/heavier APIs next.
    cost: int
    supported: bool = True


PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in (
        Provider("greenhouse", "Greenhouse", SourceType.ATS_API, 1),
        Provider("lever", "Lever", SourceType.ATS_API, 1),
        Provider("ashby", "Ashby", SourceType.ATS_API, 1),
        Provider("smartrecruiters", "SmartRecruiters", SourceType.ATS_API, 1),
        Provider("workable", "Workable", SourceType.ATS_API, 1),
        Provider("recruitee", "Recruitee", SourceType.ATS_API, 1),
        Provider("personio", "Personio", SourceType.ATS_API, 1),
        Provider("workday", "Workday", SourceType.ATS_API, 2),
        Provider("icims", "iCIMS", SourceType.ATS_API, 2),
        Provider("jibe", "iCIMS Jibe", SourceType.ATS_API, 2),
        Provider("oracle", "Oracle Cloud", SourceType.ATS_API, 2),
        Provider("amazon", "Amazon API", SourceType.PROPRIETARY_API, 2),
        Provider("microsoft", "Microsoft API", SourceType.PROPRIETARY_API, 2),
        Provider("google", "Google Careers", SourceType.PROPRIETARY_API, 2),
        Provider("apple", "Apple Jobs", SourceType.PROPRIETARY_API, 2),
        Provider("netflix", "Netflix API", SourceType.PROPRIETARY_API, 2),
        Provider("meta", "Meta Careers", SourceType.BROWSER, 3, supported=False),
        Provider("jsonld", "JSON-LD", SourceType.STATIC_HTML, 2),
        # Recognised but without an adapter: the career site works, CareerOS
        # just cannot read it unattended yet.
        Provider("jobvite", "Jobvite", SourceType.MANUAL, 9, supported=False),
        Provider("successfactors", "SuccessFactors", SourceType.MANUAL, 9, supported=False),
        Provider("eightfold", "Eightfold", SourceType.MANUAL, 9, supported=False),
        Provider("phenom", "Phenom", SourceType.MANUAL, 9, supported=False),
        Provider("bamboohr", "BambooHR", SourceType.MANUAL, 9, supported=False),
        Provider("breezyhr", "Breezy HR", SourceType.MANUAL, 9, supported=False),
        Provider("teamtailor", "Teamtailor", SourceType.MANUAL, 9, supported=False),
        Provider("jazzhr", "JazzHR", SourceType.MANUAL, 9, supported=False),
        Provider("comeet", "Comeet", SourceType.MANUAL, 9, supported=False),
        Provider("pinpoint", "Pinpoint", SourceType.MANUAL, 9, supported=False),
        Provider("rippling", "Rippling", SourceType.MANUAL, 9, supported=False),
        Provider("gem", "Gem", SourceType.MANUAL, 9, supported=False),
    )
}

SOURCE_LABELS = {
    SourceType.BROWSER.value: "Browser",
    SourceType.MANUAL.value: "Manual",
    SourceType.BLOCKED.value: "Blocked",
    SourceType.UNKNOWN.value: "Unknown",
    SourceType.STATIC_HTML.value: "Career page",
    SourceType.JSON_ENDPOINT.value: "JSON feed",
}


def provider_label(provider: str | None, source_type: str | None) -> str:
    if provider and provider in PROVIDERS:
        return PROVIDERS[provider].label
    return SOURCE_LABELS.get(source_type or "", "Unknown")


def status_bucket(career: dict[str, Any]) -> str:
    """One word for the UI: healthy | manual | degraded | failed | pending."""
    source_type = career.get("sourceType") or SourceType.UNKNOWN.value
    health = career.get("health") or Health.UNVERIFIED.value
    if health == Health.FAILED.value:
        return "failed"
    if health == Health.DEGRADED.value:
        return "degraded"
    if source_type in {SourceType.MANUAL.value, SourceType.BROWSER.value, SourceType.BLOCKED.value, SourceType.UNKNOWN.value}:
        return "manual" if career.get("lastAttemptAt") or source_type != SourceType.UNKNOWN.value else "pending"
    if health == Health.HEALTHY.value:
        return "healthy"
    return "pending"
