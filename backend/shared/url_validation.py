"""URL validation for Application Assistant navigation."""

from __future__ import annotations

import re
from urllib.parse import urlparse

BLOCKED_SCHEMES = {"file", "javascript", "data", "vbscript", "blob"}
ALLOWED_SCHEMES = {"http", "https"}

# Common job board domains that prohibit automation
PROHIBITED_DOMAINS = {
    "linkedin.com",
    "www.linkedin.com",
    "indeed.com",
    "www.indeed.com",
    "glassdoor.com",
    "www.glassdoor.com",
}

GREENHOUSE_PATTERNS = [
    r"greenhouse\.io",
    r"boards\.greenhouse\.io",
    r"job-boards\.greenhouse\.io",
    r"gh_jid=",
]

WORKDAY_PATTERNS = [
    r"myworkdayjobs\.com",
    r"/recruiting/",
]

LEVER_PATTERNS = [
    r"jobs\.lever\.co",
    r"lever\.co/",
]


def validate_url(url: str, *, allowlist: list[str] | None = None) -> tuple[bool, str]:
    """Validate a URL for safe navigation. Returns (valid, reason)."""
    if not url or not isinstance(url, str):
        return False, "URL is empty or invalid"

    url = url.strip()
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL could not be parsed"

    scheme = (parsed.scheme or "").lower()
    if scheme in BLOCKED_SCHEMES:
        return False, f"Blocked URL scheme: {scheme}"
    if scheme not in ALLOWED_SCHEMES:
        return False, f"Only http and https URLs are allowed, got: {scheme or 'none'}"

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False, "URL has no hostname"

    for prohibited in PROHIBITED_DOMAINS:
        if hostname == prohibited or hostname.endswith(f".{prohibited}"):
            return False, f"Domain {hostname} is not supported for automated applications"

    if allowlist:
        allowed = any(
            hostname == domain.lower() or hostname.endswith(f".{domain.lower()}")
            for domain in allowlist
        )
        if not allowed:
            return False, f"Domain {hostname} is not in the allowlist"

    return True, ""


def is_prohibited_platform(url: str) -> bool:
    valid, _ = validate_url(url)
    if not valid:
        return True
    hostname = (urlparse(url).hostname or "").lower()
    return any(
        hostname == d or hostname.endswith(f".{d}") for d in PROHIBITED_DOMAINS
    )


def detect_provider_from_url(url: str) -> str:
    """Detect likely ATS provider from URL."""
    lower = url.lower()
    for pattern in GREENHOUSE_PATTERNS:
        if re.search(pattern, lower):
            return "greenhouse"
    for pattern in WORKDAY_PATTERNS:
        if re.search(pattern, lower):
            return "workday"
    for pattern in LEVER_PATTERNS:
        if re.search(pattern, lower):
            return "lever"
    return "unknown"


def normalize_url(url: str) -> str:
    """Normalize URL for deduplication."""
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc.lower()}{path}"
