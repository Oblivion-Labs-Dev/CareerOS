"""Turn an aggregator listing into the employer's real application URL.

Aggregators like Himalayas republish postings that actually live on Greenhouse,
Lever or Ashby. Storing the aggregator link as the ``applicationUrl`` leaves the
job unapplyable: the automation lands on a page with no form, and in Himalayas'
case never even gets that far because the listing sits behind a Cloudflare
challenge that returns 403 to a plain fetch and "Just a moment..." to a browser.

Nothing here tries to get around that challenge. The employer's own board
publishes the same postings through a public, documented API, so the listing is
resolved by *looking the job up at the source* rather than by scraping the
aggregator:

    himalayas.app/companies/torc-robotics/jobs/senior-software-engineer-fleet-...
        -> boards-api.greenhouse.io/v1/boards/torcrobotics/jobs
        -> job-boards.greenhouse.io/torcrobotics/jobs/8783552002

The company slug needs a little coaxing (Himalayas writes "torc-robotics", the
Greenhouse board is "torcrobotics"), and the job slug is truncated, so titles
are matched on token overlap rather than equality.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("career_os.aggregator_resolve")

AGGREGATOR_HOSTS = ("himalayas.app", "weworkremotely.com", "remoteok.com", "jobicy.com")

_UA = {"User-Agent": "Mozilla/5.0 (CareerOS job import)"}
_TIMEOUT = 15.0

# Words that appear in so many engineering titles that matching on them says
# nothing about which posting this is.
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "our", "you", "your", "job", "role", "position",
    "opening", "opportunity", "remote", "hybrid", "onsite", "us", "usa",
})


def _tokens(text: str) -> set[str]:
    return {
        word
        for word in re.split(r"[^a-z0-9]+", (text or "").lower())
        if len(word) > 2 and word not in _STOPWORDS
    }


def _board_tokens(company_slug: str, company_name: str = "") -> list[str]:
    """Candidate Greenhouse board names for a company, most likely first.

    Boards are named inconsistently: Himalayas' "torc-robotics" is Greenhouse's
    "torcrobotics", while other companies keep the hyphen. Try the cheap
    variants rather than guessing one and giving up.
    """
    seeds = [s for s in (company_slug, company_name) if s]
    out: list[str] = []
    for seed in seeds:
        low = re.sub(r"[^a-z0-9\- ]", "", seed.lower()).strip()
        for candidate in (
            low.replace(" ", "").replace("-", ""),  # torcrobotics
            low.replace(" ", "-"),                   # torc-robotics
            low.replace(" ", ""),
        ):
            if candidate and candidate not in out:
                out.append(candidate)
    return out[:6]


def _parse_himalayas(url: str) -> tuple[str, str]:
    """Return (company_slug, job_slug) from a Himalayas listing URL."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    # /companies/<company>/jobs/<job-slug>
    if len(parts) >= 4 and parts[0] == "companies" and parts[2] == "jobs":
        return parts[1], parts[3]
    return "", ""


def _match_job(jobs: list[dict[str, Any]], wanted: str) -> dict[str, Any] | None:
    """Best title match, or None when nothing is convincingly close.

    The aggregator truncates its slug ("...map-validation-annotati"), so this
    scores overlap against the wanted tokens and requires most of them to be
    present. A weak best match is worse than no match: it would point the
    application at the wrong job.
    """
    wanted_tokens = _tokens(wanted)
    if not wanted_tokens:
        return None
    best, best_score = None, 0.0
    for job in jobs:
        score = len(wanted_tokens & _tokens(job.get("title") or "")) / len(wanted_tokens)
        if score > best_score:
            best, best_score = job, score
    if best is not None and best_score >= 0.6:
        return best
    logger.debug("No confident title match (best %.2f) for %r", best_score, wanted[:60])
    return None


def _greenhouse_lookup(board: str) -> list[dict[str, Any]]:
    """Public Greenhouse job board listing for one board token."""
    try:
        resp = httpx.get(
            f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
            headers=_UA,
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            return list(resp.json().get("jobs") or [])
    except Exception as exc:
        logger.debug("Greenhouse board lookup failed for %s: %s", board, exc)
    return []


def _ashby_lookup(board: str) -> list[dict[str, Any]]:
    """Public Ashby job board listing. Titles come back as `title`, links as
    `jobUrl`, so they are normalised to the Greenhouse shape used above."""
    try:
        resp = httpx.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{board}",
            headers=_UA,
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            return [
                {"title": j.get("title"), "absolute_url": j.get("jobUrl") or j.get("applyUrl")}
                for j in (resp.json().get("jobs") or [])
            ]
    except Exception as exc:
        logger.debug("Ashby board lookup failed for %s: %s", board, exc)
    return []


def _lever_lookup(board: str) -> list[dict[str, Any]]:
    """Public Lever postings feed, normalised the same way."""
    try:
        resp = httpx.get(
            f"https://api.lever.co/v0/postings/{board}?mode=json",
            headers=_UA,
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return [
                    {"title": j.get("text"), "absolute_url": j.get("hostedUrl") or j.get("applyUrl")}
                    for j in data
                ]
    except Exception as exc:
        logger.debug("Lever board lookup failed for %s: %s", board, exc)
    return []


# Tried in order. Greenhouse first because it is the most common by a wide
# margin in this queue, so most listings resolve on the first request.
_BOARD_LOOKUPS = (
    ("greenhouse", _greenhouse_lookup),
    ("ashby", _ashby_lookup),
    ("lever", _lever_lookup),
)


def is_aggregator_url(url: str) -> bool:
    host = (urlparse(url or "").netloc or "").lower()
    return any(host.endswith(h) for h in AGGREGATOR_HOSTS)


def resolve_aggregator_url(
    url: str, *, company_name: str = "", title: str = ""
) -> dict[str, Any] | None:
    """Resolve an aggregator listing to the employer's real application URL.

    Returns ``{"applicationUrl", "company", "title", "source"}`` when the
    posting is found on the employer's own board, else None so callers keep
    whatever they already had.
    """
    if not is_aggregator_url(url):
        return None

    company_slug, job_slug = _parse_himalayas(url)
    if not company_slug and company_name:
        company_slug = re.sub(r"[^a-z0-9\- ]", "", company_name.lower()).strip().replace(" ", "-")
    if not company_slug:
        return None

    # The slug is the most reliable description of the job we have: the title
    # we were given may be missing or may be the aggregator's own rewrite.
    wanted = title or (job_slug.replace("-", " ") if job_slug else "")
    if not wanted:
        return None

    for board in _board_tokens(company_slug, company_name):
        for ats_name, lookup in _BOARD_LOOKUPS:
            jobs = lookup(board)
            if not jobs:
                continue
            match = _match_job(jobs, wanted)
            if not match:
                logger.debug(
                    "%s board %s has %d jobs but none matched %r",
                    ats_name, board, len(jobs), wanted[:50],
                )
                continue
            resolved = match.get("absolute_url") or ""
            if not resolved:
                continue
            logger.info("Resolved %s -> %s", url[:70], resolved)
            return {
                "applicationUrl": resolved,
                "company": company_name or company_slug.replace("-", " ").title(),
                "title": match.get("title") or title,
                "source": f"{ats_name}:{board}",
            }

    logger.info("Could not resolve aggregator listing %s to an employer board", url[:80])
    return None
