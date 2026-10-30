"""URL validation for Application Assistant navigation."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import time
from typing import Any
from urllib.parse import urlparse

from app.config import is_production_env

logger = logging.getLogger(__name__)

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


def _address_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if ip.is_loopback:
        # A local run drives fixture servers on 127.0.0.1 (the dummy job test
        # bed, the integration tests). On a hosted box loopback is the API
        # itself, so it is refused there like any other internal address.
        return "loopback address" if is_production_env() else None
    if not ip.is_global:
        # Private ranges, link-local (169.254.169.254 is the cloud metadata
        # service), CGNAT, reserved, multicast and the unspecified address.
        return "private network address"
    return None


def private_address_reason(hostname: str, *, resolve: bool = True) -> str | None:
    """Why `hostname` must not be fetched or navigated to, or None if it may be.

    Every address the name resolves to is checked, so a public-looking name
    pointing at an internal host is refused too. A name that does not resolve
    is let through: there is nothing to reach, and the request fails on its own.
    """
    host = (hostname or "").strip().strip("[]").lower().rstrip(".")
    if not host:
        return None
    try:
        return _address_reason(ipaddress.ip_address(host))
    except ValueError:
        pass
    if host == "localhost" or host.endswith(".localhost"):
        return "loopback address" if is_production_env() else None
    if not resolve:
        return None
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return None
    for info in infos:
        try:
            reason = _address_reason(ipaddress.ip_address(info[4][0].split("%")[0]))
        except ValueError:
            continue
        if reason:
            return reason
    return None


#: Schemes a page can try to hand to the OS ("Pick an app" dialogs on Windows).
EXTERNAL_SCHEMES = ("mailto:", "tel:", "callto:", "sip:", "ms-", "slack:", "zoommtg:", "teams:", "skype:")


_HOST_REASON_TTL_SEC = 60.0
_HOST_REASON_MAX = 2048
_host_reason_cache: dict[str, tuple[float, str | None]] = {}


async def _resolved_host_reason(host: str) -> str | None:
    """private_address_reason with name resolution, cached for a minute per host."""
    now = time.monotonic()
    cached = _host_reason_cache.get(host)
    if cached and now - cached[0] < _HOST_REASON_TTL_SEC:
        return cached[1]
    reason = await asyncio.to_thread(private_address_reason, host)
    if len(_host_reason_cache) >= _HOST_REASON_MAX:
        _host_reason_cache.clear()
    _host_reason_cache[host] = (now, reason)
    return reason


async def guard_browser_request(route: Any) -> None:
    """Playwright route handler for every automated browser context.

    Aborts external-scheme hand-offs, and any request to an internal address:
    an employer page (or a redirect) must not be able to steer the browser at
    the cloud metadata service or other hosts on the machine's network. Every
    request gets the free literal-IP check; navigations, the requests that can
    leave a page sitting on an internal host, also get their name resolved.

    Every request's host is resolved, subresources included: an employer
    page's <img> or fetch() to a name that resolves internally is as much a
    probe of the machine's network as a navigation. Lookups are cached
    briefly per host. The browser does its own lookup when it connects, so a
    name that re-resolves in between (DNS rebinding) is not caught here; a
    hosted box needs an egress firewall for that.
    """
    request = route.request
    url = request.url
    blocked = None
    if url.lower().startswith(EXTERNAL_SCHEMES):
        blocked = "external scheme"
    else:
        host = urlparse(url).hostname or ""
        blocked = private_address_reason(host, resolve=False)
        if not blocked:
            blocked = await _resolved_host_reason(host)
        if blocked:
            logger.warning("Blocked browser request to %s (%s)", host, blocked)
    try:
        if blocked:
            await route.abort()
        else:
            await route.continue_()
    except Exception:
        pass


async def refuse_private_http_request(request: Any) -> None:
    """httpx request event hook: refuse internal targets on every hop,
    redirects included, for server-side fetches of user-supplied URLs."""
    host = request.url.host or ""
    blocked = await asyncio.to_thread(private_address_reason, host)
    if blocked:
        raise PermissionError(f"Refusing to fetch {host}: {blocked}")


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

    blocked = private_address_reason(hostname)
    if blocked:
        return False, f"Refusing to open {hostname}: {blocked}"

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
