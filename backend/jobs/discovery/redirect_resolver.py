"""Resolve job-board tracking redirectors to the employer's real application URL.

Indeed hands back an apply URL for nearly every posting, but a large share of
them point at a tracking hop rather than the employer — `grnh.se` (Greenhouse's
own shortener), `click.appcast.io`, `jsv3.recruitics.com`, `tnl2.jometer.com`.
Two things go wrong if those are stored as-is:

  * The ATS handling downstream cannot tell a Greenhouse posting from an
    arbitrary link, so a posting that is perfectly automatable looks like an
    unknown career page.
  * Dedup breaks. `canonical_ats_posting_id` reads the ATS id off the URL, and a
    tracking hop exposes none, so the same job arrives repeatedly under
    different tracking ids. Observed live: three identical Uber postings
    differing only by the `jz` parameter on `tnl2.jometer.com`.

Following the hop fixes both at once — measured, `grnh.se` lands on
`job-boards.greenhouse.io/<company>/jobs/<id>`, exactly the shape the pipeline
handles best.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx

logger = logging.getLogger("career_os.job_discover.redirect_resolver")

# Only these are followed. Resolving every apply URL would double the request
# count of a scrape for no benefit — an employer URL is already the destination.
REDIRECTOR_HOSTS: frozenset[str] = frozenset({
    "grnh.se",
    "click.appcast.io",
    "jsv3.recruitics.com",
    "tnl2.jometer.com",
    "job.jometer.com",
    "www.jobs2careers.com",
    "click.indeed.com",
    "sjobs.brassring.com",
})

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}

# A tracking link is stable, so the same hop is worth resolving only once per
# process. Bounded so a long scrape cannot grow it without limit.
_MAX_CACHE = 5000
_cache: dict[str, str] = {}

# Appcast answers 200 with the destination inside the document rather than an
# HTTP 3xx, so `follow_redirects` never moves and the hop looks like a dead end.
# Verified live: a Walmart posting hid a `walmart.wd504.myworkdayjobs.com` URL
# this way — a board the pipeline already handles.
_BODY_REDIRECT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Appcast's shape: the destination is the last argument of a navigateTo()
    # call, while the assignment itself is to a variable — so matching on
    # `location.href = "..."` alone never sees it.
    #   navigateTo(window.parent, window, "https://careers.humana.com/...")
    re.compile(r"""navigateTo\([^)]*?['"](https?://[^'"]+)['"]""", re.I),
    re.compile(r"""window\.location(?:\.href)?\s*=\s*['"](https?://[^'"]+)['"]""", re.I),
    # "about:blank" is used as a decoy in the same script, so only absolute
    # http(s) destinations count here.
    re.compile(r"""location\.replace\(\s*['"](https?://[^'"]+)['"]""", re.I),
    re.compile(r"""http-equiv=['"]refresh['"][^>]*?url=(https?://[^'">\s]+)""", re.I),
)

# Hosts worth pulling out of a document even when no redirect statement matched.
_ATS_HOST_HINT = re.compile(
    r"""https?://[^\s'"<>]*?(?:greenhouse\.io|lever\.co|ashbyhq\.com|myworkdayjobs\.com"""
    r"""|icims\.com|smartrecruiters\.com|workable\.com|taleo\.net|jobvite\.com)[^\s'"<>]*""",
    re.I,
)


def _unwrap_nested_url(url: str) -> str:
    """Pull the real destination out of a wrapper's query string.

    Appcast hands back links shaped like
    `careers.walmart.com?r=https://walmart.wd504.myworkdayjobs.com/...` — the
    wrapper is a landing page, the parameter is the applyable posting.
    """
    try:
        qs = parse_qs(urlparse(url).query)
    except ValueError:
        return url
    for key in ("r", "url", "redirect", "target", "destination"):
        for candidate in qs.get(key, []):
            decoded = unquote(candidate)
            if decoded.startswith("http"):
                return decoded
    return url


def _extract_body_redirect(html: str, base_url: str) -> str:
    """Find the destination a 200-with-embedded-redirect page points at."""
    if not html:
        return ""
    for pattern in _BODY_REDIRECT_PATTERNS:
        match = pattern.search(html)
        if match:
            candidate = unquote(match.group(1).strip())
            if candidate.startswith("http"):
                return candidate
    match = _ATS_HOST_HINT.search(html)
    if match:
        return unquote(match.group(0))
    return ""


def is_redirector(url: str) -> bool:
    if not url:
        return False
    try:
        host = (urlparse(url).netloc or "").lower()
    except ValueError:
        return False
    return host in REDIRECTOR_HOSTS


async def resolve_redirect(client: httpx.AsyncClient, url: str, *, timeout: float = 15.0) -> str:
    """Return the URL a tracking hop lands on, or the original URL unchanged.

    Never raises: an unresolvable hop is not a reason to drop an otherwise good
    posting, so the caller keeps whatever it already had.
    """
    if not is_redirector(url):
        return url
    cached = _cache.get(url)
    if cached:
        return cached

    resolved = url
    try:
        # HEAD is enough to walk an HTTP redirect chain and avoids pulling the
        # whole page; some hops reject it or answer 200 without moving, so fall
        # back to GET, which is also what makes the in-document case below
        # visible.
        resp = await client.head(url, follow_redirects=True, timeout=timeout, headers=_UA)
        if resp.status_code >= 400 or str(resp.url) == url:
            resp = await client.get(url, follow_redirects=True, timeout=timeout, headers=_UA)

        if resp.status_code < 400:
            final = str(resp.url)
            if final and not is_redirector(final):
                resolved = final
            else:
                # Still on the hop: the destination is inside the document.
                body = resp.text if resp.request.method == "GET" else ""
                if not body:
                    body = (
                        await client.get(url, follow_redirects=True, timeout=timeout, headers=_UA)
                    ).text
                embedded = _extract_body_redirect(body, url)
                if embedded and not is_redirector(embedded):
                    resolved = embedded

        resolved = _unwrap_nested_url(resolved)
    except Exception as exc:
        logger.debug("Could not resolve redirector %s: %s", url[:80], exc)

    if len(_cache) < _MAX_CACHE:
        _cache[url] = resolved
    return resolved


async def resolve_all(
    client: httpx.AsyncClient,
    urls: list[str],
    *,
    concurrency: int = 8,
    timeout: float = 15.0,
) -> dict[str, str]:
    """Resolve many hops at once, bounded so a scrape does not stampede a host."""
    targets = [u for u in dict.fromkeys(urls) if is_redirector(u)]
    if not targets:
        return {}

    sem = asyncio.Semaphore(concurrency)

    async def _one(u: str) -> tuple[str, str]:
        async with sem:
            return u, await resolve_redirect(client, u, timeout=timeout)

    pairs = await asyncio.gather(*(_one(u) for u in targets), return_exceptions=True)
    return {u: r for pair in pairs if not isinstance(pair, BaseException) for u, r in [pair]}
