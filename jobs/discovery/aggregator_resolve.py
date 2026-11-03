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
from urllib.parse import parse_qs, urlparse

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
        words = [w for w in re.split(r"[\s\-]+", low) if w]
        candidates = [
            low.replace(" ", "").replace("-", ""),  # torcrobotics
            low.replace(" ", "-"),                   # torc-robotics
            low.replace(" ", ""),
        ]
        # Boards are very often registered under a shortened trading name rather
        # than the full legal one: "Parallel Web Systems" publishes on Ashby as
        # `parallel`, so neither `parallelwebsystems` nor `parallel-web-systems`
        # ever matched and the posting looked unresolvable. Falling back to the
        # first word (and first two) is safe here because `_match_job` still
        # requires a strong title overlap — an unrelated company that happens to
        # own the short token contributes no convincing match. Verified: a
        # `parallel` Greenhouse board exists for an automotive firm and is
        # correctly rejected on title.
        if len(words) > 1:
            candidates.append(words[0])
            candidates.append("".join(words[:2]))
            candidates.append("-".join(words[:2]))
        for candidate in candidates:
            if candidate and candidate not in out:
                out.append(candidate)
    return out[:8]


def _parse_himalayas(url: str) -> tuple[str, str]:
    """Return (company_slug, job_slug) from a Himalayas listing URL."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    # /companies/<company>/jobs/<job-slug>
    if len(parts) >= 4 and parts[0] == "companies" and parts[2] == "jobs":
        return parts[1], parts[3]
    return "", ""


# Words that appear in so many engineering titles that sharing one says nothing
# about which posting this is. Distinct from _STOPWORDS, which strips filler:
# these are meaningful words that are simply not *discriminating*.
_GENERIC_ROLE_TOKENS = frozenset({
    "senior", "sr", "junior", "jr", "staff", "principal", "lead", "mid",
    "level", "engineer", "engineering", "developer", "development", "software",
    "member", "technical", "specialist", "analyst", "architect", "consultant",
    "manager", "director", "head", "associate", "intern", "contract",
    "fulltime", "full", "time", "part", "team", "group", "new", "grad",
    "i", "ii", "iii", "iv", "one", "two", "three",
})


def _distinctive_tokens(text: str) -> set[str]:
    """The words in a title that actually identify *which* role it is."""
    return _tokens(text) - _GENERIC_ROLE_TOKENS


def _match_by_distinctive_token(
    jobs: list[dict[str, Any]], wanted: str
) -> dict[str, Any] | None:
    """Fall back to an unambiguous domain match when titles were rewritten.

    Aggregators frequently republish a posting under their own wording:
    jaabz lists one Parallel role as "Senior Security Engineer (Application &
    AI Agent Security)" while the employer's own board calls it "Member of
    Technical Staff, Product Security". Those share only the word "security",
    so the overlap test above rejects a correct match.

    This accepts a match only when it is *unambiguous*: exactly one posting on
    the board shares any distinctive (non-boilerplate) word with the wanted
    title. If two candidates share one, the board has more than one role in
    that area and guessing between them risks applying to the wrong job, so
    nothing is returned. Generic words like "senior" or "engineer" are excluded
    precisely because nearly every posting shares them.
    """
    wanted_distinctive = _distinctive_tokens(wanted)
    if not wanted_distinctive:
        return None

    candidates = [
        job for job in jobs
        if wanted_distinctive & _distinctive_tokens(job.get("title") or "")
    ]
    if len(candidates) != 1:
        if len(candidates) > 1:
            logger.debug(
                "Distinctive-token fallback found %d candidates for %r — too "
                "ambiguous to pick one", len(candidates), wanted[:60],
            )
        return None
    logger.info(
        "Matched %r to %r on a unique distinctive token",
        wanted[:50], (candidates[0].get("title") or "")[:50],
    )
    return candidates[0]


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
    # Strict overlap missed. Before giving up, try the rewritten-title case —
    # it only returns something when exactly one posting on the board is
    # plausibly the same role, so an ambiguous board still yields nothing.
    return _match_by_distinctive_token(jobs, wanted)


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


# Board listings are reused constantly (the same employer shows up across many
# postings in one scrape), and a miss is as worth caching as a hit.
_BOARD_LISTING_CACHE: dict[tuple[str, str], list[dict[str, Any]]] = {}


def _cached_lookup(ats_name: str, lookup: Any, board: str) -> list[dict[str, Any]]:
    key = (ats_name, board)
    if key not in _BOARD_LISTING_CACHE:
        try:
            _BOARD_LISTING_CACHE[key] = lookup(board)
        except Exception:
            _BOARD_LISTING_CACHE[key] = []
    return _BOARD_LISTING_CACHE[key]


def resolve_by_company_and_title(
    company_name: str, title: str, *, max_board_candidates: int = 3
) -> dict[str, Any] | None:
    """Find an employer's real posting from just a company name and a job title.

    This is what turns a LinkedIn discovery into something applyable. LinkedIn's
    guest cards carry no employer apply URL and its detail endpoint does not
    either (verified on live postings), but the company name plus the title is
    enough to look the posting up on the employer's own board.

    Measured on 20 live LinkedIn results: 6 resolved this way. The misses are
    overwhelmingly large enterprises on Workday/Taleo/iCIMS, which publish no
    equivalent open listing endpoint — those stay unresolved rather than being
    guessed at.
    """
    if not company_name or not title:
        return None

    for board in _board_tokens(company_name, company_name)[:max_board_candidates]:
        for ats_name, lookup in _BOARD_LOOKUPS:
            listing = _cached_lookup(ats_name, lookup, board)
            if not listing:
                continue
            match = _match_job(listing, title)
            if not match:
                continue
            resolved = match.get("absolute_url") or ""
            if not resolved:
                continue
            logger.info(
                "Resolved %s / %s -> %s", company_name[:30], title[:40], resolved[:70]
            )
            return {
                "applicationUrl": resolved,
                "company": company_name,
                "title": match.get("title") or title,
                "source": f"{ats_name}:{board}",
            }
    return None


def resolve_company_branded_greenhouse_url(
    url: str, *, company_name: str = "", title: str = ""
) -> dict[str, Any] | None:
    """Resolve a company's own branded careers page back to its Greenhouse URL.

    Some employers mirror their Greenhouse postings on their own domain
    (``coinbase.com/careers/positions/7847431?gh_jid=7847431``) without an
    iframe or a discoverable form on that page — the automation correctly
    finds nothing to fill, but the posting is real and automatable at its
    actual Greenhouse address. The mirror page always carries the numeric
    Greenhouse job id in a ``gh_jid`` query parameter, so this is an *id*
    lookup against the employer's public board (unlike ``resolve_aggregator_url``
    above, which has no id to work with and has to fuzzy-match on title).
    """
    qs = parse_qs(urlparse(url).query)
    gh_jid = (qs.get("gh_jid") or [""])[0].strip()
    if not gh_jid or not gh_jid.isdigit():
        return None

    for board in _board_tokens(company_name, company_name):
        jobs = _greenhouse_lookup(board)
        if not jobs:
            continue
        match = next((j for j in jobs if str(j.get("id") or "") == gh_jid), None)
        if not match:
            continue
        resolved = match.get("absolute_url") or ""
        if not resolved:
            continue
        logger.info("Resolved company-branded page %s -> %s", url[:70], resolved)
        return {
            "applicationUrl": resolved,
            "company": company_name or board,
            "title": match.get("title") or title,
            "source": f"greenhouse:{board}",
        }
    logger.info("Could not resolve gh_jid=%s on %s to a Greenhouse board", gh_jid, url[:70])
    return None


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
