"""Local H1B / visa sponsorship signal detection from job description text."""

from __future__ import annotations

import re
from typing import Literal, TypedDict

H1bStatus = Literal["likely", "unlikely", "unknown"]


class H1bSponsorshipResult(TypedDict):
    status: H1bStatus
    label: str
    reason: str
    signals: list[str]


LIKELY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bh-?1b\b", re.I), "H-1B mentioned"),
    (re.compile(r"\bvisa sponsorship\b", re.I), "Visa sponsorship"),
    (re.compile(r"\bwill sponsor\b", re.I), "Will sponsor"),
    (re.compile(r"\bsponsorship (?:is )?available\b", re.I), "Sponsorship available"),
    (re.compile(r"\bopen to (?:visa )?sponsor", re.I), "Open to sponsorship"),
    (re.compile(r"\b(?:opt|cpt)\b", re.I), "OPT/CPT friendly"),
    (re.compile(r"\bemployment-based visa\b", re.I), "Employment visa"),
    (re.compile(r"\bperm\b", re.I), "PERM mentioned"),
    (re.compile(r"\be-?verify\b", re.I), "E-Verify"),
]

UNLIKELY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bno (?:visa )?sponsorship\b", re.I), "No sponsorship stated"),
    (re.compile(r"\bunable to sponsor\b", re.I), "Unable to sponsor"),
    (re.compile(r"\bnot (?:able to )?sponsor\b", re.I), "Will not sponsor"),
    (re.compile(r"\bwithout sponsorship\b", re.I), "Without sponsorship"),
    (re.compile(r"\bdo not sponsor\b", re.I), "Do not sponsor"),
    (re.compile(r"\bdoes not sponsor\b", re.I), "Does not sponsor"),
    (re.compile(r"\bnot provide sponsorship\b", re.I), "No sponsorship provided"),
    (re.compile(r"\b(?:us|u\.s\.?) citizens? only\b", re.I), "US citizens only"),
    (
        re.compile(r"\bmust be (?:a )?(?:us|u\.s\.?) (?:citizen|permanent resident)\b", re.I),
        "Citizens/PR only",
    ),
    (
        re.compile(r"\bauthorized to work (?:in the )?(?:us|u\.s\.?) without sponsorship\b", re.I),
        "No sponsorship required",
    ),
    (re.compile(r"\bno immigration sponsorship\b", re.I), "No immigration sponsorship"),
]


def check_h1b_sponsorship(text: str) -> H1bSponsorshipResult:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return {
            "status": "unknown",
            "label": "H1B unknown",
            "reason": "No job description to analyze.",
            "signals": [],
        }

    likely: list[str] = []
    unlikely: list[str] = []

    for pattern, signal in LIKELY_PATTERNS:
        if pattern.search(normalized):
            likely.append(signal)

    for pattern, signal in UNLIKELY_PATTERNS:
        if pattern.search(normalized):
            unlikely.append(signal)

    if unlikely:
        return {
            "status": "unlikely",
            "label": "Unlikely H1B",
            "reason": unlikely[0],
            "signals": unlikely[:4],
        }

    if likely:
        return {
            "status": "likely",
            "label": "H1B friendly",
            "reason": likely[0],
            "signals": likely[:4],
        }

    return {
        "status": "unknown",
        "label": "H1B unclear",
        "reason": "No explicit sponsorship language found.",
        "signals": [],
    }


def apply_h1b_fields(job: dict) -> dict:
    """Attach h1b* fields derived from title + description."""
    text = f"{job.get('title', '')} {job.get('description', '')}".strip()
    result = check_h1b_sponsorship(text)
    return {
        **job,
        "h1bStatus": result["status"],
        "h1bLabel": result["label"],
        "h1bReason": result["reason"],
        "h1bSignals": result["signals"],
    }
