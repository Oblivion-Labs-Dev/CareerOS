"""US-only location filtering for job discovery scrapers."""

from __future__ import annotations

import re

# ── US-only location filter ─────────────────────────────────────────────────

US_STATES_ABBR: set[str] = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}

_US_PAT = re.compile(
    r"\b(?:united\s+states|usa|u\.s\.a\.?|u\.s\.)\b", re.IGNORECASE
)
_STATE_NAMES_PAT = re.compile(
    r"\b(?:alabama|alaska|arizona|arkansas|california|colorado|connecticut|"
    r"delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|"
    r"kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|"
    r"mississippi|missouri|montana|nebraska|nevada|new\s+hampshire|"
    r"new\s+jersey|new\s+mexico|new\s+york|north\s+carolina|north\s+dakota|"
    r"ohio|oklahoma|oregon|pennsylvania|rhode\s+island|south\s+carolina|"
    r"south\s+dakota|tennessee|texas|utah|vermont|virginia|washington|"
    r"west\s+virginia|wisconsin|wyoming|district\s+of\s+columbia)\b",
    re.IGNORECASE,
)
_FOREIGN_PAT = re.compile(
    r"\b(?:canada|uk|united\s+kingdom|india|germany|france|japan|australia|"
    r"singapore|ireland|netherlands|brazil|mexico|china|hong\s+kong|taiwan|"
    r"south\s+korea|israel|sweden|switzerland|spain|italy|poland|czech|"
    r"austria|belgium|denmark|norway|finland|portugal|london|toronto|"
    r"vancouver|berlin|munich|paris|dublin|amsterdam|tokyo|sydney|"
    r"melbourne|bangalore|hyderabad|tel\s+aviv|stockholm|zurich|madrid|"
    r"warsaw|prague|vienna|brussels|copenhagen|oslo|helsinki|lisbon|"
    r"mumbai|pune|delhi|chennai|gurgaon|noida|ontario|british\s+columbia|"
    r"quebec|alberta|manila|bangkok|jakarta|buenos\s+aires|bogot[aá]|"
    r"s[aã]o\s+paulo|shanghai|beijing|shenzhen)\b",
    re.IGNORECASE,
)


def is_us_location(location: str) -> bool:
    """Check if a location string appears to be in the United States.

    Returns True for US locations, Remote (without foreign qualifier),
    and unknown/empty locations (benefit of the doubt).
    """
    if not location or not location.strip():
        return True  # Unknown → include
    loc = location.strip()
    if _US_PAT.search(loc):
        return True
    if _STATE_NAMES_PAT.search(loc):
        return True
    # Check for 2-letter state abbreviations in comma/pipe-separated parts
    parts = [p.strip() for p in loc.replace("|", ",").split(",")]
    for part in parts:
        if part.upper() in US_STATES_ABBR:
            return True
    # "Remote" without a foreign country → include
    if re.search(r"\bremote\b", loc, re.IGNORECASE) and not _FOREIGN_PAT.search(loc):
        return True
    # Explicitly foreign → exclude
    if _FOREIGN_PAT.search(loc):
        return False
    return True  # Can't determine → include
