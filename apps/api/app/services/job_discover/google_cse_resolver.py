"""Last-resort posting lookup through Google Programmable Search.

Only for the residue. `resolve_by_company_and_title` already finds postings on
Greenhouse/Lever/Ashby through their public listing APIs — free, unlimited, and
it resolved 8 of 25 live LinkedIn discoveries. What it cannot resolve is large
enterprises on Workday/Taleo/iCIMS (General Motors, U.S. Bank and Collins
Aerospace all missed), because those platforms publish no open listing endpoint.
A search index is the only remaining way in.

The free Custom Search tier is **100 queries per day**, so this is deliberately
the narrowest possible consumer of it:

  * it runs only after the free ATS lookup has already failed
  * the search engine is restricted to applyable ATS hosts, so a hit is a job
    posting rather than a careers landing page or a LinkedIn mirror
  * every call is counted against a persisted daily budget, so a restart cannot
    quietly double the spend
  * results are cached, including misses

Disabled unless both `GOOGLE_CSE_API_KEY` and `GOOGLE_CSE_ENGINE_ID` are set.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("career_os.job_discover.google_cse")

GOOGLE_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"

# Persisted so the budget survives a process restart — the quota is daily and
# per-project, not per-process.
QUOTA_KV_KEY = "google_cse_daily_usage"

# The free tier is 100/day. Stopping a little short leaves room for anything
# else on the same project and avoids hard 429s.
DEFAULT_DAILY_BUDGET = int(os.environ.get("GOOGLE_CSE_DAILY_BUDGET", "90"))

# A hit only counts if it lands somewhere an application can actually be filed.
APPLYABLE_HOSTS = (
    "myworkdayjobs.com",
    "taleo.net",
    "icims.com",
    "jobvite.com",
    "successfactors.com",
    "brassring.com",
    "avature.net",
    "eightfold.ai",
    "phenompeople.com",
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "smartrecruiters.com",
    "workable.com",
)

_STOPWORDS = frozenset({
    "senior", "sr", "staff", "principal", "lead", "engineer", "software",
    "the", "and", "for", "with", "our", "job", "role", "position", "remote",
})

_cache: dict[tuple[str, str], dict[str, Any] | None] = {}


def is_configured() -> bool:
    return bool(os.environ.get("GOOGLE_CSE_API_KEY") and os.environ.get("GOOGLE_CSE_ENGINE_ID"))


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _significant(text: str) -> set[str]:
    return {
        w for w in re.split(r"[^a-z0-9]+", (text or "").lower())
        if len(w) > 2 and w not in _STOPWORDS
    }


def get_usage(db: Any) -> tuple[int, int]:
    """Return (used_today, budget). Resets automatically on a new UTC day."""
    from app.db.store import get_kv

    record = get_kv(db, QUOTA_KV_KEY) or {}
    if record.get("date") != _today():
        return 0, DEFAULT_DAILY_BUDGET
    return int(record.get("count") or 0), DEFAULT_DAILY_BUDGET


def _spend(db: Any, n: int = 1) -> None:
    from app.db.store import get_kv, set_kv

    record = get_kv(db, QUOTA_KV_KEY) or {}
    count = int(record.get("count") or 0) if record.get("date") == _today() else 0
    set_kv(db, QUOTA_KV_KEY, {"date": _today(), "count": count + n})


def _is_applyable(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return any(h in host for h in APPLYABLE_HOSTS)


def _pick_best(items: list[dict[str, Any]], company: str, title: str) -> dict[str, Any] | None:
    """Accept a result only when it plausibly *is* this posting.

    A search index will happily return the company's job-search page or a
    different opening. Requiring overlap with the title's distinctive words —
    and refusing anything that is not on an applyable host — keeps a wrong
    posting from being queued as if it were the right one.
    """
    wanted = _significant(title)
    if not wanted:
        return None
    company_words = _significant(company)
    best: tuple[float, dict[str, Any]] | None = None

    for item in items:
        link = item.get("link") or ""
        if not _is_applyable(link):
            continue
        haystack = f"{item.get('title') or ''} {item.get('snippet') or ''}"
        found = _significant(haystack)
        title_overlap = len(wanted & found) / len(wanted)
        if title_overlap < 0.5:
            continue
        # Company agreement is a tiebreak, not a gate: a Workday URL often
        # carries the tenant name rather than the display name.
        company_hit = bool(company_words & found) or any(
            w in link.lower() for w in company_words
        )
        score = title_overlap + (0.25 if company_hit else 0.0)
        if best is None or score > best[0]:
            best = (score, item)

    if best is None:
        return None
    return best[1]


def company_from_ats_url(url: str) -> str:
    """Recover the employer from an ATS URL's own shape.

    A search result gives a page title, not a structured company field, but the
    applyable hosts all encode the employer in the URL: the first path segment
    on Greenhouse/Lever/Ashby/SmartRecruiters, the subdomain on Workday/Taleo/
    iCIMS. Verified against live URLs from each.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    host = (parsed.netloc or "").lower()
    parts = [p for p in (parsed.path or "").split("/") if p]

    if any(h in host for h in ("greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com")):
        first = parts[0] if parts else ""
        # Greenhouse's embed endpoint puts no company in the path.
        return "" if first in ("embed", "jobs") else first
    if "myworkdayjobs.com" in host or "taleo.net" in host:
        return host.split(".")[0]
    if "icims.com" in host:
        return host.split(".")[0].replace("careers-", "").replace("careers", "")
    return ""


async def search_recent_postings(
    client: httpx.AsyncClient,
    db: Any,
    query: str,
    *,
    days_old: int = 7,
    max_pages: int = 3,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Discover recent applyable postings for one query.

    This is the higher-leverage use of the daily quota: one query returns up to
    ten *new* postings, where a per-job lookup spends the same unit resolving a
    single posting already known. Because the search engine is restricted to
    applyable ATS hosts, every result is a job page that can be applied to — no
    second mapping step is needed.

    `dateRestrict` is what keeps this pointed at new listings instead of
    re-surfacing the same indexed pages every day.
    """
    if not is_configured() or not query:
        return []

    used, budget = get_usage(db)
    if used >= budget:
        logger.info("Google CSE daily budget spent (%d/%d); skipping discovery", used, budget)
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    pages = min(max_pages, max(0, budget - used))

    for page in range(pages):
        params = {
            "key": os.environ["GOOGLE_CSE_API_KEY"],
            "cx": os.environ["GOOGLE_CSE_ENGINE_ID"],
            "q": query,
            "num": 10,
            "start": page * 10 + 1,
            "dateRestrict": f"d{int(days_old)}",
        }
        try:
            _spend(db, 1)
            resp = await client.get(GOOGLE_CSE_ENDPOINT, params=params, timeout=timeout)
            if resp.status_code != 200:
                if resp.status_code == 429:
                    logger.warning("Google CSE 429 — upstream quota exhausted")
                else:
                    logger.warning("Google CSE discovery returned %s", resp.status_code)
                break
            items = resp.json().get("items") or []
        except Exception as exc:
            logger.debug("Google CSE discovery failed for %r: %s", query[:50], exc)
            break

        if not items:
            break
        for item in items:
            link = item.get("link") or ""
            if not link or link in seen or not _is_applyable(link):
                continue
            seen.add(link)
            out.append({
                "url": link,
                "title": item.get("title") or "",
                "snippet": item.get("snippet") or "",
                "company": company_from_ats_url(link),
            })
        if len(items) < 10:
            break

    return out


async def resolve_via_google(
    client: httpx.AsyncClient,
    db: Any,
    company: str,
    title: str,
    *,
    timeout: float = 15.0,
) -> dict[str, Any] | None:
    """Find an applyable posting for one company/title, or None.

    Returns None rather than raising for every failure mode — no credentials, a
    spent budget, an API error, or no convincing match — because an unresolved
    posting is an ordinary outcome here, not an error.
    """
    if not is_configured() or not company or not title:
        return None

    cache_key = (company.strip().lower(), title.strip().lower())
    if cache_key in _cache:
        return _cache[cache_key]

    used, budget = get_usage(db)
    if used >= budget:
        logger.info("Google CSE daily budget spent (%d/%d); skipping lookup", used, budget)
        return None

    params = {
        "key": os.environ["GOOGLE_CSE_API_KEY"],
        "cx": os.environ["GOOGLE_CSE_ENGINE_ID"],
        "q": f'"{company}" "{title}"',
        "num": 10,
    }

    result: dict[str, Any] | None = None
    try:
        _spend(db, 1)
        resp = await client.get(GOOGLE_CSE_ENDPOINT, params=params, timeout=timeout)
        if resp.status_code == 429:
            logger.warning("Google CSE returned 429 — daily quota exhausted upstream")
        elif resp.status_code != 200:
            logger.warning("Google CSE returned %s", resp.status_code)
        else:
            match = _pick_best(resp.json().get("items") or [], company, title)
            if match:
                result = {
                    "applicationUrl": match.get("link"),
                    "company": company,
                    "title": match.get("title") or title,
                    "source": "google_cse",
                }
                logger.info(
                    "Google CSE resolved %s / %s -> %s",
                    company[:30], title[:40], str(match.get("link"))[:70],
                )
    except Exception as exc:
        logger.debug("Google CSE lookup failed for %s/%s: %s", company[:30], title[:30], exc)

    _cache[cache_key] = result
    return result
