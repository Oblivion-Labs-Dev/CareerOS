"""JobPilot — Unified multi-ATS job scraper.

Scrapes jobs from:
  - Greenhouse (public JSON API)
  - Lever (public JSON API)
  - Ashby (public JSON API)
  - SmartRecruiters (public JSON API)
  - Workday (hidden JSON API)
  - Workable (public widget API)

All scrapers use httpx (async HTTP) — no browser needed for API-based scraping.
"""

import asyncio
import json
import os
import random
import re
import ssl
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path

import httpx

# ── Configuration ────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "job_discover"
CONFIG_FILE = DATA_DIR / "company_config.json"
SLUGS_FILE = DATA_DIR / "company_slugs.txt"

# ⚠️ DUPLICATION (intentional, do NOT blindly sync): this ROLE_FILTERS is a
# SEPARATE, narrower copy of role_classifier.ROLE_PATTERNS. They have already
# diverged on purpose — this scrape-time filter is intentionally tighter (no
# 'hw', fewer swe/tpm/ux patterns) to keep the scrape lean. role_classifier is
# the broader source of truth used for classification/Night Shift. Changing one
# does NOT change the other; reconcile deliberately, never mechanically.
ROLE_FILTERS = {
    "swe": [
        r"\bsenior\s+software\s+engineer\b",
        r"\bbackend\s+engineer\b",
        r"\bplatform\s+engineer\b",
        r"\bsoftware\s+development\s+engineer\b",
        r"\bsoftware\s+engineer\b",
        r"\bsde\b",
        r"\bswe\b",
        r"\bbackend\s+developer\b",
        r"\bplatform\s+developer\b",
        r"\bfull[\s\-]?stack\s+engineer\b",
        r"\binfrastructure\s+engineer\b",
        r"\bstaff\s+software\s+engineer\b",
        r"\bprincipal\s+software\s+engineer\b",
        r"\blead\s+software\s+engineer\b",
        r"\bsite\s+reliability\s+engineer\b",
        r"\bsre\b",
    ],
    "pm": [],
    "product": [],
    "tpm": [],
    "ux": [],
    "presales": [],
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

SCRAPER_TASK_TIMEOUT_SEC = 90


# ── Helpers ──────────────────────────────────────────────────────────────────

async def fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_attempts: int = 3,
    **kwargs,
) -> httpx.Response | None:
    """GET a board, retrying the failures that are worth retrying.

    This module previously had no retry logic at all: every board was fetched
    exactly once, so one transient blip meant that employer contributed nothing
    for the whole run - and an empty result is indistinguishable from "this
    company has no open roles", so the loss was invisible.

    Retries connection errors, timeouts, 429 and 5xx with exponential backoff
    and jitter. Deliberately does not retry other 4xx: a 404 board slug will
    still be 404 on the third attempt, and retrying only delays the run.

    Returns the response, or None when every attempt failed - callers already
    treat a falsy response as "no jobs from this board".

    Wraps each attempt in `asyncio.wait_for` on top of httpx's own timeout:
    httpx's read timeout only bounds the idle gap *between* chunks, not the
    total time to read a response body, so a server that trickles bytes
    slowly enough to never leave one chunk idle past the read timeout (a
    tarpit, deliberate or not) can keep a `client.get()` call hanging far
    past the configured timeout - and since this all runs on the API's
    single asyncio event loop, one such hang froze request handling
    (including `/health`) for the whole process, not just this scrape.
    `wait_for` gives every attempt a hard wall-clock ceiling regardless of
    where inside httpx it is stuck.
    """
    per_attempt_timeout = kwargs.get("timeout")
    if not isinstance(per_attempt_timeout, (int, float)):
        per_attempt_timeout = 20.0
    hard_deadline = per_attempt_timeout + 10.0
    delay = 0.6
    for attempt in range(max_attempts):
        try:
            response = await asyncio.wait_for(client.get(url, **kwargs), timeout=hard_deadline)
            if response.status_code < 400:
                return response
            retryable = response.status_code == 429 or response.status_code >= 500
            if not retryable or attempt == max_attempts - 1:
                return response
        except (httpx.TimeoutException, httpx.TransportError, TimeoutError):
            if attempt == max_attempts - 1:
                return None
        # Jitter so a hundred board tasks do not retry in lockstep.
        await asyncio.sleep(delay + random.uniform(0, delay * 0.3))
        delay = min(delay * 2, 6.0)
    return None


def build_verified_ssl_context() -> "ssl.SSLContext":
    """A TLS context that actually verifies the boards we fetch from.

    Both scrapers used to set check_hostname=False and verify_mode=CERT_NONE,
    which turns off certificate verification for every outbound request. That is
    not a cosmetic weakness here: the apply URL carried in a scraped posting is
    what Autopilot later opens in a real browser and submits a resume into, so
    anyone able to sit between this process and a job board could redirect an
    application. Verification is on.

    CAREEROS_SCRAPER_CA_BUNDLE points at a PEM bundle for environments behind a
    TLS-inspecting proxy, which is the legitimate reason someone reaches for
    CERT_NONE. That keeps verification on against a trusted root instead of
    disabling it.
    """
    bundle = os.environ.get("CAREEROS_SCRAPER_CA_BUNDLE", "").strip()
    if bundle and Path(bundle).is_file():
        return ssl.create_default_context(cafile=bundle)
    return ssl.create_default_context()


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def load_greenhouse_slugs() -> list[str]:
    """Legacy: load from company_slugs.txt for backward compatibility."""
    if SLUGS_FILE.exists():
        return [line.strip() for line in SLUGS_FILE.read_text().splitlines() if line.strip()]
    return []


def compile_role_patterns(role_keys: list[str] | None = None) -> list[re.Pattern]:
    patterns = []
    if role_keys:
        for key in role_keys:
            patterns.extend(ROLE_FILTERS.get(key, []))
    else:
        for group in ROLE_FILTERS.values():
            patterns.extend(group)
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def matches_title(title: str, compiled: list[re.Pattern]) -> bool:
    """Check if title matches any role pattern AND is not excluded.

    Uses the shared role_classifier exclusion list to reject titles like
    'Construction Project Manager', 'Financial Analyst', 'Legal Counsel'
    that superficially match a role keyword but are irrelevant.
    """
    from app.services.job_discover.role_classifier import _is_excluded
    if _is_excluded(title):
        return False
    return any(p.search(title) for p in compiled)


def strip_html(html: str) -> str:
    if not html:
        return ""
    text = unescape(html)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<li>", "\n- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_recent(ts: str, cutoff: datetime) -> bool:
    """Check if a timestamp string is more recent than the cutoff."""
    if not ts:
        return True  # If no timestamp, include it
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt >= cutoff
    except (ValueError, TypeError):
        return True  # Can't parse → include


def s(v) -> str:
    """Coerce any value to string for SQLite safety."""
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return str(v)


# ── US-only location filter ─────────────────────────────────────────────────

US_STATES_ABBR = {
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


# ── Greenhouse Scraper ───────────────────────────────────────────────────────

def flatten_greenhouse(job: dict, company: str) -> dict:
    loc = job.get("location", {})
    location = loc.get("name", "") if isinstance(loc, dict) else str(loc or "")
    departments = job.get("departments") or []
    metadata = {m.get("name", ""): m.get("value") for m in (job.get("metadata") or [])}
    return {
        "greenhouse_id": s(job.get("id", "")),
        "company": company,
        "title": job.get("title", ""),
        "location": location,
        "department": ", ".join(d.get("name", "") for d in departments),
        "url": job.get("absolute_url", ""),
        "description": strip_html(job.get("content", "")),
        "updated_at": job.get("updated_at", ""),
        "first_published": job.get("first_published", ""),
        "employment_type": s(metadata.get("Employment Type", "")),
        "salary_range": s(metadata.get("Salary Range", metadata.get("Compensation Range", ""))),
    }


def _parse_greenhouse_board(
    payload: bytes,
    company: str,
    compiled: list[re.Pattern],
    cutoff: datetime,
) -> list[dict]:
    """Pure-CPU half of a board scrape, safe to run off the event loop."""
    data = json.loads(payload)
    jobs = []
    for job in data.get("jobs", []):
        title = job.get("title", "")
        ts = job.get("updated_at", "")
        if not matches_title(title, compiled):
            continue
        if not is_recent(ts, cutoff):
            continue
        jobs.append(flatten_greenhouse(job, company))
    return jobs


async def scrape_greenhouse(
    client: httpx.AsyncClient,
    company: str,
    slug: str,
    compiled: list[re.Pattern],
    cutoff: datetime,
    role_keys: list[str] | None,
) -> list[dict]:
    """Scrape one Greenhouse board via their public JSON API."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    try:
        resp = await fetch_with_retry(client, url, timeout=15)
        if resp is None or resp.status_code != 200:
            return []
        # With content=true a board runs to several megabytes, and both the JSON
        # parse and strip_html over every description are pure CPU. Dozens of
        # boards are gathered concurrently, so leaving this on the event loop
        # starved every API request — /health included — for as long as
        # discovery ran, and the UI sat on "Loading applications…".
        return await asyncio.to_thread(
            _parse_greenhouse_board, resp.content, company, compiled, cutoff
        )
    except Exception:
        return []


# ── Lever Scraper ────────────────────────────────────────────────────────────

def flatten_lever(job: dict, company: str) -> dict:
    categories = job.get("categories", {})
    return {
        "greenhouse_id": s(job.get("id", "")),
        "company": company,
        "title": job.get("text", ""),
        "location": categories.get("location", ""),
        "department": categories.get("department", ""),
        "url": job.get("hostedUrl", job.get("applyUrl", "")),
        "description": strip_html(job.get("descriptionPlain", job.get("description", ""))),
        "updated_at": "",
        "first_published": datetime.fromtimestamp(
            job.get("createdAt", 0) / 1000, tz=UTC
        ).isoformat() if job.get("createdAt") else "",
        "employment_type": categories.get("commitment", ""),
        "salary_range": "",
    }


async def scrape_lever(
    client: httpx.AsyncClient,
    company: str,
    slug: str,
    compiled: list[re.Pattern],
    cutoff: datetime,
    role_keys: list[str] | None,
) -> list[dict]:
    """Scrape one Lever board via their public JSON API."""
    url = f"https://api.lever.co/v0/postings/{slug}"
    try:
        resp = await fetch_with_retry(client, url, timeout=15)
        if resp is None or resp.status_code != 200:
            return []
        postings = resp.json()
        if not isinstance(postings, list):
            return []
        jobs = []
        for job in postings:
            title = job.get("text", "")
            # Lever uses createdAt (epoch ms)
            created = job.get("createdAt", 0)
            if created:
                ts = datetime.fromtimestamp(created / 1000, tz=UTC).isoformat()
            else:
                ts = ""
            if not matches_title(title, compiled):
                continue
            if not is_recent(ts, cutoff):
                continue
            jobs.append(flatten_lever(job, company))
        return jobs
    except Exception:
        return []


# ── Ashby Scraper ────────────────────────────────────────────────────────────

def flatten_ashby(job: dict, company: str) -> dict:
    return {
        "greenhouse_id": s(job.get("id", "")),
        "company": company,
        "title": job.get("title", ""),
        "location": job.get("location", ""),
        "department": job.get("department", job.get("departmentName", "")),
        "url": f"https://jobs.ashbyhq.com/{company}/{job.get('id', '')}",
        "description": strip_html(job.get("descriptionHtml", job.get("descriptionPlain", ""))),
        "updated_at": job.get("updatedAt", ""),
        "first_published": job.get("publishedAt", ""),
        "employment_type": job.get("employmentType", ""),
        "salary_range": "",
    }


async def scrape_ashby(
    client: httpx.AsyncClient,
    company: str,
    slug: str,
    compiled: list[re.Pattern],
    cutoff: datetime,
    role_keys: list[str] | None,
) -> list[dict]:
    """Scrape one Ashby board via their public JSON API."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    try:
        resp = await fetch_with_retry(client, url, timeout=15)
        if resp is None or resp.status_code != 200:
            return []
        data = resp.json()
        jobs = []
        for job in data.get("jobs", []):
            title = job.get("title", "")
            ts = job.get("updatedAt", job.get("publishedAt", ""))
            if not matches_title(title, compiled):
                continue
            if not is_recent(ts, cutoff):
                continue
            jobs.append(flatten_ashby(job, company))
        return jobs
    except Exception:
        return []


# ── SmartRecruiters Scraper ──────────────────────────────────────────────────

def flatten_smartrecruiters(job: dict, company: str) -> dict:
    loc = job.get("location", {})
    location_parts = [loc.get("city", ""), loc.get("region", ""), loc.get("country", "")]
    location = ", ".join(p for p in location_parts if p)
    return {
        "greenhouse_id": s(job.get("id", job.get("uuid", ""))),
        "company": company,
        "title": job.get("name", ""),
        "location": location,
        "department": job.get("department", {}).get("label", "") if isinstance(job.get("department"), dict) else "",
        "url": job.get("ref", job.get("applyUrl", "")),
        "description": "",  # SR listing API doesn't include description
        "updated_at": job.get("releasedDate", ""),
        "first_published": job.get("releasedDate", ""),
        "employment_type": job.get("typeOfEmployment", {}).get("label", "") if isinstance(job.get("typeOfEmployment"), dict) else "",
        "salary_range": "",
    }


async def scrape_smartrecruiters(
    client: httpx.AsyncClient,
    company: str,
    slug: str,
    compiled: list[re.Pattern],
    cutoff: datetime,
    role_keys: list[str] | None,
) -> list[dict]:
    """Scrape one SmartRecruiters board via their public API."""
    all_jobs = []
    offset = 0
    limit = 100

    while True:
        url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?offset={offset}&limit={limit}"
        try:
            resp = await fetch_with_retry(client, url, timeout=15)
            if resp is None or resp.status_code != 200:
                break
            data = resp.json()
            postings = data.get("content", [])
            if not postings:
                break

            for job in postings:
                title = job.get("name", "")
                ts = job.get("releasedDate", "")
                if not matches_title(title, compiled):
                    continue
                if not is_recent(ts, cutoff):
                    continue
                all_jobs.append(flatten_smartrecruiters(job, company))

            total = data.get("totalFound", 0)
            offset += limit
            if offset >= total:
                break
        except Exception:
            break

    return all_jobs


# ── Workday Scraper ──────────────────────────────────────────────────────────

def flatten_workday(job: dict, company: str, base_url: str) -> dict:
    external_path = job.get("externalPath", "")
    url = f"https://{base_url}{external_path}" if external_path else ""
    posted = job.get("postedOn", "")
    # Workday uses relative dates like "Posted 2 Days Ago" — normalize
    location_parts = []
    for loc in (job.get("locationsText", "") or "").split("|"):
        loc = loc.strip()
        if loc:
            location_parts.append(loc)

    return {
        "greenhouse_id": s(job.get("bulletFields", [""])[0] if job.get("bulletFields") else ""),
        "company": company,
        "title": job.get("title", ""),
        "location": " | ".join(location_parts),
        "department": "",
        "url": url,
        "description": "",  # Workday list API doesn't include descriptions
        "updated_at": "",
        "first_published": posted,
        "employment_type": job.get("timeType", ""),
        "salary_range": "",
    }


async def scrape_workday(
    client: httpx.AsyncClient,
    company: str,
    config: dict,
    compiled: list[re.Pattern],
    cutoff: datetime,
    role_keys: list[str] | None,
) -> list[dict]:
    """Scrape one Workday board via their hidden JSON API.

    Endpoint: https://{host}/wday/cxs/{company}/{board}/jobs
    Method: POST with JSON body {"limit": N, "offset": 0}
    Key: Must send Origin + Referer headers or you get 406/422.
    """
    host = config["host"]
    wd_company = config["company"]
    board = config["board"]
    url = f"https://{host}/wday/cxs/{wd_company}/{board}/jobs"

    # Workday requires browser-like Origin/Referer or it blocks with 406/422
    wd_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": f"https://{host}",
        "Referer": f"https://{host}/{board}",
    }

    all_jobs = []
    offset = 0
    limit = 20  # Workday max per request

    while True:
        payload = {"limit": limit, "offset": offset, "appliedFacets": {}, "searchText": ""}
        try:
            resp = await client.post(url, json=payload, headers=wd_headers, timeout=20)
            if resp.status_code not in (200, 201):
                break
            data = resp.json()
            postings = data.get("jobPostings", [])
            if not postings:
                break

            for job in postings:
                title = job.get("title", "")
                if not matches_title(title, compiled):
                    continue
                # Workday doesn't give ISO dates in list — include if title matches
                all_jobs.append(flatten_workday(job, company, host))

            total = data.get("total", 0)
            offset += limit
            if offset >= total or offset >= 200:  # Cap at 200 to avoid rate limits
                break
        except Exception:
            break

    return all_jobs


# ── Workable Scraper ─────────────────────────────────────────────────────────

def flatten_workable(job: dict, company: str) -> dict:
    return {
        "greenhouse_id": s(job.get("id", job.get("shortcode", ""))),
        "company": company,
        "title": job.get("title", ""),
        "location": f"{job.get('city', '')} {job.get('country', '')}".strip(),
        "department": job.get("department", ""),
        "url": job.get("url", job.get("application_url", "")),
        "description": strip_html(job.get("description", "")),
        "updated_at": job.get("published_on", ""),
        "first_published": job.get("published_on", ""),
        "employment_type": job.get("employment_type", ""),
        "salary_range": "",
    }


async def scrape_workable(
    client: httpx.AsyncClient,
    company: str,
    slug: str,
    compiled: list[re.Pattern],
    cutoff: datetime,
    role_keys: list[str] | None,
) -> list[dict]:
    """Scrape one Workable board via their widget API."""
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    try:
        resp = await fetch_with_retry(client, url, timeout=15)
        if resp is None or resp.status_code != 200:
            return []
        data = resp.json()
        jobs = []
        for job in data.get("jobs", []):
            title = job.get("title", "")
            ts = job.get("published_on", "")
            if not matches_title(title, compiled):
                continue
            if not is_recent(ts, cutoff):
                continue
            jobs.append(flatten_workable(job, company))
        return jobs
    except Exception:
        return []


# ── YC Work at a Startup Scraper ────────────────────────────────────────────

async def scrape_yc_jobs(
    client: httpx.AsyncClient,
    compiled: list[re.Pattern],
    cutoff: datetime,
    role_keys: list[str] | None,
    max_results: int = 200,
) -> list[dict]:
    """Scrape Y Combinator Work at a Startup via their Algolia-backed API.

    The public search API is at workatastartup.com/companies.json
    and uses Algolia under the hood. We use the public JSON endpoint.
    """
    all_jobs = []
    page = 0
    max_pages = 5

    while len(all_jobs) < max_results and page < max_pages:
        try:
            # YC WAAS has a public JSON API
            resp = await fetch_with_retry(client, 
                "https://www.workatastartup.com/companies/jobs",
                params={
                    "page": page,
                    "query": "",
                    "hasEquity": "false",
                    "hasSalary": "false",
                    "industry": "B2B,Consumer,Education,Enterprise,Fintech,Healthcare,Real+Estate",
                    "interviewProcess": "",
                    "jobType": "fulltime",
                    "layout": "list-compact",
                    "sortBy": "created_desc",
                    "tab": "any",
                    "usVisaOnly": "false",
                },
                headers={"Accept": "application/json"},
                timeout=20,
            )
            if resp is None or resp.status_code != 200:
                break
            data = resp.json()

            jobs_list = data if isinstance(data, list) else data.get("jobs", data.get("results", []))
            if not jobs_list:
                break

            for job in jobs_list:
                title = job.get("title", "")
                if not matches_title(title, compiled):
                    continue

                company_name = job.get("company_name", job.get("startup_name", ""))
                ts = job.get("created_at", job.get("updated_at", ""))

                all_jobs.append({
                    "greenhouse_id": f"yc-{job.get('id', '')}",
                    "company": company_name.lower().replace(" ", "") if company_name else "yc-startup",
                    "title": title,
                    "location": job.get("pretty_eng_type", job.get("location", "Remote")),
                    "department": "",
                    "url": job.get("url", f"https://www.workatastartup.com/jobs/{job.get('id', '')}"),
                    "description": strip_html(job.get("description", "")),
                    "updated_at": ts,
                    "first_published": ts,
                    "employment_type": job.get("type", "Full-time"),
                    "salary_range": "",
                })

            page += 1
            if len(jobs_list) < 20:
                break
        except Exception:
            break

    return all_jobs[:max_results]


# ── Wellfound (AngelList) Scraper ───────────────────────────────────────────

async def scrape_wellfound(
    client: httpx.AsyncClient,
    compiled: list[re.Pattern],
    cutoff: datetime,
    role_keys: list[str] | None,
    max_results: int = 200,
) -> list[dict]:
    """Scrape Wellfound (formerly AngelList Talent) via their GraphQL API.

    Uses the public /graphql endpoint that powers wellfound.com search.
    """
    all_jobs = []
    page = 1

    # Build search query from role filters
    search_roles = ["Product Manager", "Software Engineer", "UX Designer"]
    if role_keys:
        role_map = {
            "pm": "Product Manager",
            "swe": "Software Engineer",
            "ux": "UX Designer",
            "tpm": "Program Manager",
            "product": "Product",
            "presales": "Solutions Engineer",
        }
        search_roles = [role_map.get(k, k) for k in role_keys if k in role_map]

    for search_term in search_roles:
        page = 1
        max_pages = 5
        while len(all_jobs) < max_results and page <= max_pages:
            try:
                # Wellfound has a public GraphQL API
                query = {
                    "query": """
                    query JobSearchQuery($query: String!, $page: Int!) {
                        talent {
                            jobListings(filters: {
                                query: $query,
                                locationSlugs: ["united-states"],
                                remote: true,
                                page: $page
                            }) {
                                edges {
                                    node {
                                        id
                                        title
                                        slug
                                        description
                                        primaryRoleTitle
                                        liveStartAt
                                        locationNames
                                        compensation
                                        remote
                                        startup {
                                            name
                                            slug
                                            companySize
                                        }
                                    }
                                }
                                pageInfo {
                                    hasNextPage
                                }
                            }
                        }
                    }
                    """,
                    "variables": {"query": search_term, "page": page},
                }

                resp = await client.post(
                    "https://wellfound.com/graphql",
                    json=query,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Origin": "https://wellfound.com",
                        "Referer": "https://wellfound.com/jobs",
                    },
                    timeout=20,
                )

                if resp is None or resp.status_code != 200:
                    # Fallback: try the public noscript/REST search
                    resp2 = await fetch_with_retry(client, 
                        f"https://wellfound.com/role/{search_term.lower().replace(' ', '-')}",
                        params={"page": page},
                        headers={"Accept": "application/json"},
                        timeout=20,
                    )
                    if resp2.status_code != 200:
                        break
                    data = resp2.json() if resp2.headers.get("content-type", "").startswith("application/json") else {}
                    jobs_list = data.get("jobs", data.get("results", []))
                    if not jobs_list:
                        break

                    for job in jobs_list:
                        title = job.get("title", "")
                        if not matches_title(title, compiled):
                            continue
                        company_name = job.get("company_name", job.get("startup_name", ""))
                        ts = job.get("live_start_at", job.get("created_at", ""))
                        all_jobs.append({
                            "greenhouse_id": f"wf-{job.get('id', '')}",
                            "company": company_name.lower().replace(" ", "") if company_name else "wellfound-startup",
                            "title": title,
                            "location": ", ".join(job.get("location_names", [])) if isinstance(job.get("location_names"), list) else job.get("location", "Remote"),
                            "department": "",
                            "url": f"https://wellfound.com/jobs/{job.get('slug', job.get('id', ''))}",
                            "description": strip_html(job.get("description", "")),
                            "updated_at": ts,
                            "first_published": ts,
                            "employment_type": "Full-time",
                            "salary_range": job.get("compensation", ""),
                        })
                    page += 1
                    continue

                data = resp.json()
                edges = (
                    data.get("data", {})
                    .get("talent", {})
                    .get("jobListings", {})
                    .get("edges", [])
                )
                has_next = (
                    data.get("data", {})
                    .get("talent", {})
                    .get("jobListings", {})
                    .get("pageInfo", {})
                    .get("hasNextPage", False)
                )

                if not edges:
                    break

                for edge in edges:
                    node = edge.get("node", {})
                    title = node.get("title", "")
                    if not matches_title(title, compiled):
                        continue
                    startup = node.get("startup", {}) or {}
                    company_name = startup.get("name", "")
                    ts = node.get("liveStartAt", "")
                    loc_names = node.get("locationNames", [])

                    all_jobs.append({
                        "greenhouse_id": f"wf-{node.get('id', '')}",
                        "company": company_name.lower().replace(" ", "") if company_name else "wellfound-startup",
                        "title": title,
                        "location": ", ".join(loc_names) if isinstance(loc_names, list) else str(loc_names or "Remote"),
                        "department": node.get("primaryRoleTitle", ""),
                        "url": f"https://wellfound.com/jobs/{node.get('slug', node.get('id', ''))}",
                        "description": strip_html(node.get("description", "")),
                        "updated_at": ts,
                        "first_published": ts,
                        "employment_type": "Full-time",
                        "salary_range": node.get("compensation", ""),
                    })

                page += 1
                if not has_next:
                    break
            except Exception:
                break

    return all_jobs[:max_results]


def _confidently_us_location(location: str) -> bool:
    """Stricter US check for aggregator boards that skew heavily non-US.

    Unlike is_us_location (which gives ambiguous/unknown locations the
    benefit of the doubt), this requires an explicit US signal — a bare
    "Remote" or "Worldwide" from a global board is not enough, per the
    user's standing requirement that Autopilot only surface US postings.
    """
    if not location:
        return False
    loc = location.strip()
    if _US_PAT.search(loc):
        return True
    if _STATE_NAMES_PAT.search(loc):
        return True
    # Deliberately split on comma only, not "|" — some boards (Arbeitnow)
    # format location as "<ISO country code> | <city>" (e.g. "DE | München"),
    # and 2-letter country codes collide with US state abbreviations (DE ==
    # Delaware). Comma-separated "City, ST" is the reliable US convention.
    parts = [p.strip().upper() for p in loc.split(",")]
    return any(part in US_STATES_ABBR for part in parts)


# ── Arbeitnow (free, no API key) ────────────────────────────────────────────

async def scrape_arbeitnow(
    client: httpx.AsyncClient,
    compiled: list[re.Pattern],
    cutoff: datetime,
    role_keys: list[str] | None,
    max_results: int = 200,
) -> list[dict]:
    """Scrape Arbeitnow's free public job board API (no key required).

    Docs: https://www.arbeitnow.com/api/job-board-api
    Paginated via `page`; each page returns ~100 postings sorted by recency.
    """
    all_jobs: list[dict] = []
    page = 1
    max_pages = 5

    while len(all_jobs) < max_results and page <= max_pages:
        try:
            resp = await fetch_with_retry(client, 
                "https://www.arbeitnow.com/api/job-board-api",
                params={"page": page},
                headers={"Accept": "application/json"},
                timeout=20,
            )
            if resp is None or resp.status_code != 200:
                break
            data = resp.json()
            postings = data.get("data") or []
            if not postings:
                break

            for job in postings:
                title = job.get("title", "")
                if not matches_title(title, compiled):
                    continue

                created = job.get("created_at")
                ts = ""
                if created:
                    try:
                        ts = datetime.fromtimestamp(int(created), tz=UTC).isoformat()
                    except (ValueError, TypeError, OSError):
                        ts = ""
                if not is_recent(ts, cutoff):
                    continue

                company_name = job.get("company_name", "")
                location = job.get("location", "") or ("Remote" if job.get("remote") else "")
                if not _confidently_us_location(location):
                    continue

                all_jobs.append({
                    "greenhouse_id": f"arbeitnow-{job.get('slug', '')}",
                    "company": company_name.lower().replace(" ", "") if company_name else "arbeitnow-listing",
                    "title": title,
                    "location": location,
                    "department": "",
                    "url": job.get("url", ""),
                    "description": strip_html(job.get("description", "")),
                    "updated_at": ts,
                    "first_published": ts,
                    "employment_type": ", ".join(job.get("job_types") or []) or "Full-time",
                    "salary_range": "",
                })

            page += 1
            if len(postings) < 50:
                break
        except Exception:
            break

    return all_jobs[:max_results]


# ── Remotive (free, no API key) ─────────────────────────────────────────────

async def scrape_remotive(
    client: httpx.AsyncClient,
    compiled: list[re.Pattern],
    cutoff: datetime,
    role_keys: list[str] | None,
    max_results: int = 200,
) -> list[dict]:
    """Scrape Remotive's free public remote-jobs API (no key required).

    Docs: https://remotive.com/api/remote-jobs
    Supports a `search` query, but we fetch broadly and filter locally so
    role matching stays consistent with the other scrapers.
    """
    all_jobs: list[dict] = []

    try:
        resp = await fetch_with_retry(client, 
            "https://remotive.com/api/remote-jobs",
            headers={"Accept": "application/json"},
            timeout=20,
        )
        if resp is None or resp.status_code != 200:
            return []
        data = resp.json()
        postings = data.get("jobs") or []

        for job in postings:
            title = job.get("title", "")
            if not matches_title(title, compiled):
                continue

            ts = job.get("publication_date", "")
            if not is_recent(ts, cutoff):
                continue

            location = job.get("candidate_required_location", "") or "Remote"
            if not _confidently_us_location(location):
                continue

            all_jobs.append({
                "greenhouse_id": f"remotive-{job.get('id', '')}",
                "company": (job.get("company_name") or "").lower().replace(" ", "") or "remotive-listing",
                "title": title,
                "location": location,
                "department": job.get("category", ""),
                "url": job.get("url", ""),
                "description": strip_html(job.get("description", "")),
                "updated_at": ts,
                "first_published": ts,
                "employment_type": job.get("job_type", "") or "Full-time",
                "salary_range": job.get("salary", ""),
            })
            if len(all_jobs) >= max_results:
                break
    except Exception:
        return all_jobs

    return all_jobs[:max_results]


# ── Unified Scraper Entry Point ──────────────────────────────────────────────

# Per-source outcome of the most recent scrape_jobs() call, for observability.
# scrape_jobs used to swallow every per-source exception into a bare `except:
# pass`, which is how four adapter-based sources sat broken and invisible.
LAST_SOURCE_REPORT: dict[str, dict] = {"counts": {}, "errors": {}, "scrapedAt": None}


def _serpapi_key() -> str:
    """SerpApi key, if one is configured. Google Jobs bills per call, so the
    adapter stays out of the run entirely when no key is present."""
    import os

    key = os.environ.get("SERPAPI_KEY") or os.environ.get("SERPAPI_API_KEY") or ""
    return key.strip()


def _as_job_dicts(result) -> list[dict]:
    """Coerce a source's result into US-filtered plain dicts for persistence.

    Sources come in two shapes: the legacy scrape_* functions return dicts,
    while JobSourceAdapter subclasses return NormalizedJob dataclasses. The
    persistence path (_normalize_scraped_job) only speaks dict, so everything
    is converted here before it can reach on_batch.

    The US filter is applied here too. It used to run only on scrape_jobs'
    return value, which nothing persists — so non-US postings reached the
    index anyway. Filtering at the point of persistence makes what is stored
    match what this module documents itself as returning.
    """
    if not isinstance(result, list):
        return []
    jobs: list[dict] = []
    for item in result:
        if hasattr(item, "to_dict"):
            job = item.to_dict()
        elif isinstance(item, dict):
            job = item
        else:
            continue
        if is_us_location(job.get("location", "")):
            jobs.append(job)
    return jobs



async def scrape_jobs(
    companies: list[str] | None = None,
    role_keys: list[str] | None = None,
    hours: int = 168,
    concurrency: int = 5,
    progress_callback: Callable[[int, int], None] | None = None,
    on_batch: Callable[[list[dict]], Awaitable[None] | None] | None = None,
) -> list[dict]:
    """Scrape all configured ATS platforms. Returns flat list of job dicts.

    Args:
        companies: Optional list of company names to scrape.
                   If None, scrape all companies in company_config.json.
        role_keys: Filter by role category ('pm', 'swe', 'ux', etc.).
                   If None, match all roles in ROLE_FILTERS.
        hours: Only include jobs updated within this many hours (max 2160 / 90 days / 3 months).
        concurrency: Max concurrent HTTP requests.
        progress_callback: Called with (done, total) as scraping progresses.
    """
    config = load_config()
    hours = max(1, min(int(hours), 2160))
    compiled = compile_role_patterns(role_keys)
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    sem = asyncio.Semaphore(concurrency)

    # Build task list from all ATS platforms
    task_labels = []

    # Greenhouse — also fall back to company_slugs.txt for legacy support
    gh_map = config.get("greenhouse", {})
    if companies:
        gh_companies = {c: gh_map[c] for c in companies if c in gh_map}
    else:
        gh_companies = dict(gh_map)
        # Add any slugs from the legacy file not already in config
        for slug in load_greenhouse_slugs():
            if slug not in gh_companies:
                gh_companies[slug] = slug
    for company, _slug in gh_companies.items():
        task_labels.append(f"greenhouse/{company}")

    # Lever
    lever_map = config.get("lever", {})
    if companies:
        lever_companies = {c: lever_map[c] for c in companies if c in lever_map}
    else:
        lever_companies = dict(lever_map)
    for company, _slug in lever_companies.items():
        task_labels.append(f"lever/{company}")

    # Ashby
    ashby_map = config.get("ashby", {})
    if companies:
        ashby_companies = {c: ashby_map[c] for c in companies if c in ashby_map}
    else:
        ashby_companies = dict(ashby_map)
    for company, _slug in ashby_companies.items():
        task_labels.append(f"ashby/{company}")

    # SmartRecruiters
    sr_map = config.get("smartrecruiters", {})
    if companies:
        sr_companies = {c: sr_map[c] for c in companies if c in sr_map}
    else:
        sr_companies = dict(sr_map)
    for company, _slug in sr_companies.items():
        task_labels.append(f"smartrecruiters/{company}")

    # Workday
    wd_map = config.get("workday", {})
    if companies:
        wd_companies = {c: wd_map[c] for c in companies if c in wd_map}
    else:
        wd_companies = dict(wd_map)
    for company in wd_companies:
        task_labels.append(f"workday/{company}")

    # Workable
    wa_map = config.get("workable", {})
    if companies:
        wa_companies = {c: wa_map[c] for c in companies if c in wa_map}
    else:
        wa_companies = dict(wa_map)
    for company, _slug in wa_companies.items():
        task_labels.append(f"workable/{company}")

    # iCIMS
    ic_map = config.get("icims", {})
    if companies:
        ic_companies = {c: ic_map[c] for c in companies if c in ic_map}
    else:
        ic_companies = dict(ic_map)
    for company in ic_companies:
        task_labels.append(f"icims/{company}")

    # Oracle Cloud Recruiting
    or_map = config.get("oracle", {})
    if companies:
        or_companies = {c: or_map[c] for c in companies if c in or_map}
    else:
        or_companies = dict(or_map)
    for company in or_companies:
        task_labels.append(f"oracle/{company}")

    # GitHub machine-readable feeds (not company-scoped)
    gh_feeds = {} if companies else dict(config.get("github_feeds", {}))
    for feed_name in gh_feeds:
        task_labels.append(f"github_feed/{feed_name}")

    len(task_labels)
    completed = 0
    all_jobs = []
    progress_total = [0]
    source_counts: dict[str, int] = {}
    source_errors: dict[str, str] = {}

    async def run_with_sem(label: str, coro):
        nonlocal completed
        async with sem:
            try:
                result = await asyncio.wait_for(coro, timeout=SCRAPER_TASK_TIMEOUT_SEC)
            except TimeoutError:
                source_errors[label] = f"timed out after {SCRAPER_TASK_TIMEOUT_SEC}s"
                result = []
            except Exception as exc:
                source_errors[label] = f"{type(exc).__name__}: {exc}"
                result = []
            completed += 1
            if progress_callback and progress_total[0]:
                progress_callback(completed, progress_total[0])
            # Adapter-based sources (Jobicy, Himalayas, WeWorkRemotely, Hacker
            # News) return NormalizedJob dataclasses, not dicts. on_batch feeds
            # straight into _normalize_scraped_job, which calls .get() on each
            # item — so an unconverted dataclass raised AttributeError, the
            # except below swallowed it, and the source silently contributed
            # nothing. The snapshot is written ONLY by on_batch (the list this
            # function returns is used for counts), so a swallowed batch means
            # the jobs are lost entirely. Convert here, once, for every source.
            batch = _as_job_dicts(result)
            if batch:
                source_counts[label] = source_counts.get(label, 0) + len(batch)
            if on_batch and batch:
                try:
                    batch_result = on_batch(batch)
                    if asyncio.iscoroutine(batch_result):
                        await batch_result
                except Exception as exc:
                    source_errors[label] = f"on_batch {type(exc).__name__}: {exc}"
            return batch

    # Run all scrapers concurrently with shared httpx client
    ssl_ctx = build_verified_ssl_context()

    async with httpx.AsyncClient(
        headers=HEADERS,
        verify=ssl_ctx,
        follow_redirects=True,
        timeout=httpx.Timeout(20.0, connect=10.0),
        # Socket-level reconnects, under the status-code retries in
        # fetch_with_retry. The two layers cover different failures.
        transport=httpx.AsyncHTTPTransport(retries=2, verify=ssl_ctx),
    ) as client:
        # Imported here rather than at module scope: the adapters import
        # helpers back out of this module, and a top-level import would make
        # that circular.
        from app.services.job_discover.sources.github_feed import GitHubFeedSource
        from app.services.job_discover.sources.hackernews import HackerNewsSource
        from app.services.job_discover.sources.himalayas import HimalayasSource
        from app.services.job_discover.sources.icims import ICIMSSource
        from app.services.job_discover.sources.jobicy import JobicySource
        from app.services.job_discover.sources.oracle import OracleSource
        from app.services.job_discover.sources.serpapi_google_jobs import SerpApiGoogleJobsSource
        from app.services.job_discover.sources.weworkremotely import WeWorkRemotelySource

        coros = []

        # Greenhouse tasks
        for company, slug in gh_companies.items():
            coros.append(run_with_sem(
                f"greenhouse/{company}",
                scrape_greenhouse(client, company, slug, compiled, cutoff, role_keys),
            ))

        # Lever tasks
        for company, slug in lever_companies.items():
            coros.append(run_with_sem(
                f"lever/{company}",
                scrape_lever(client, company, slug, compiled, cutoff, role_keys),
            ))

        # Ashby tasks
        for company, slug in ashby_companies.items():
            coros.append(run_with_sem(
                f"ashby/{company}",
                scrape_ashby(client, company, slug, compiled, cutoff, role_keys),
            ))

        # SmartRecruiters tasks
        for company, slug in sr_companies.items():
            coros.append(run_with_sem(
                f"smartrecruiters/{company}",
                scrape_smartrecruiters(client, company, slug, compiled, cutoff, role_keys),
            ))

        # Workday tasks
        for company, wd_config in wd_companies.items():
            coros.append(run_with_sem(
                f"workday/{company}",
                scrape_workday(client, company, wd_config, compiled, cutoff, role_keys),
            ))

        # Workable tasks
        for company, slug in wa_companies.items():
            coros.append(run_with_sem(
                f"workable/{company}",
                scrape_workable(client, company, slug, compiled, cutoff, role_keys),
            ))

        # iCIMS tasks
        for company, ic_config in ic_companies.items():
            coros.append(run_with_sem(
                f"icims/{company}",
                ICIMSSource().fetch_jobs(client, company, ic_config, compiled, cutoff, role_keys),
            ))

        # Oracle Cloud Recruiting tasks
        for company, or_config in or_companies.items():
            coros.append(run_with_sem(
                f"oracle/{company}",
                OracleSource().fetch_jobs(client, company, or_config, compiled, cutoff, role_keys),
            ))

        # YC Work at a Startup
        coros.append(run_with_sem(
            "yc/workatastartup",
            scrape_yc_jobs(client, compiled, cutoff, role_keys, max_results=200),
        ))

        # Wellfound (AngelList)
        coros.append(run_with_sem(
            "wellfound/all",
            scrape_wellfound(client, compiled, cutoff, role_keys, max_results=200),
        ))

        # Arbeitnow (free, no API key)
        coros.append(run_with_sem(
            "arbeitnow/all",
            scrape_arbeitnow(client, compiled, cutoff, role_keys, max_results=200),
        ))

        # Remotive (free, no API key)
        coros.append(run_with_sem(
            "remotive/all",
            scrape_remotive(client, compiled, cutoff, role_keys, max_results=200),
        ))

        # Jobicy (free remote jobs API, no API key)
        coros.append(run_with_sem(
            "jobicy/all",
            JobicySource().fetch_jobs(client, compiled_patterns=compiled, cutoff=cutoff, role_keys=role_keys),
        ))

        # Hacker News 'Who is Hiring?' (free Algolia API, no API key)
        coros.append(run_with_sem(
            "hackernews/whoishiring",
            HackerNewsSource().fetch_jobs(client, compiled_patterns=compiled, cutoff=cutoff, role_keys=role_keys),
        ))

        # Himalayas (live public API, 100k+ remote jobs)
        coros.append(run_with_sem(
            "himalayas/all",
            HimalayasSource().fetch_jobs(client, company="all", config={}, compiled_patterns=compiled, cutoff=cutoff, role_keys=role_keys),
        ))

        # WeWorkRemotely (live developer & devops RSS feeds)
        coros.append(run_with_sem(
            "weworkremotely/all",
            WeWorkRemotelySource().fetch_jobs(client, company="all", config={}, compiled_patterns=compiled, cutoff=cutoff, role_keys=role_keys),
        ))

        # GitHub machine-readable job feeds (SimplifyJobs New-Grad-Positions et al.)
        for feed_name, feed_config in gh_feeds.items():
            coros.append(run_with_sem(
                f"github_feed/{feed_name}",
                GitHubFeedSource().fetch_jobs(client, feed_name, feed_config, compiled, cutoff, role_keys),
            ))

        # Google Jobs via SerpApi — only when an API key is configured, since
        # every call bills against a quota.
        if _serpapi_key():
            coros.append(run_with_sem(
                "serpapi_google_jobs/all",
                SerpApiGoogleJobsSource().fetch_jobs(client, "all", {}, compiled, cutoff, role_keys),
            ))

        progress_total[0] = len(coros)

        # Run all concurrently
        results = await asyncio.gather(*coros, return_exceptions=True)

        for result in results:
            # run_with_sem already converted every source's output to
            # US-filtered dicts, so nothing further is needed here.
            if isinstance(result, list):
                all_jobs.extend(result)

    LAST_SOURCE_REPORT["counts"] = dict(source_counts)
    LAST_SOURCE_REPORT["errors"] = dict(source_errors)
    LAST_SOURCE_REPORT["scrapedAt"] = datetime.now(UTC).isoformat()

    all_jobs.sort(key=lambda j: j.get("updated_at", j.get("first_published", "")), reverse=True)
    return all_jobs
