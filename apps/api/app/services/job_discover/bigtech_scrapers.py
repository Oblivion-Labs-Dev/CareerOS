"""JobPilot — Big Tech career page scrapers.

These companies use proprietary ATS systems that don't have public APIs.
We use Playwright to intercept their internal JSON endpoints.

Supports:
  - Apple (jobs.apple.com)
  - Meta (metacareers.com)
  - Google (careers.google.com)
  - Amazon (amazon.jobs)
  - Netflix (jobs.netflix.com — also on Lever for some roles)
  - Microsoft (careers.microsoft.com)

Strategy: Navigate to career search page → intercept XHR/fetch calls →
          parse the JSON response → no HTML scraping needed.
"""

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx

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


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


# ── Shared helpers ───────────────────────────────────────────────────────────

def strip_html(html: str) -> str:
    if not html:
        return ""
    from html import unescape
    text = unescape(html)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<li>", "\n- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


ROLE_PATTERNS = [
    r"\bproduct\s+manager\b", r"\btechnical\s+product\s+manager\b",
    r"\bassociate\s+product\s+manager\b", r"\bprogram\s+manager\b",
    r"\btpm\b", r"\bux\s+designer\b", r"\bux\s+researcher\b",
    r"\bproduct\s+designer\b", r"\bsoftware\s+engineer\b",
    r"\bsolutions\s+engineer\b", r"\bsolutions\s+architect\b",
]
COMPILED_ROLES = [re.compile(p, re.IGNORECASE) for p in ROLE_PATTERNS]


def matches_role(title: str, role_keys: list[str] | None = None) -> bool:
    """Check if title matches any role filter. Always filters — never stores junk.

    Uses the shared exclusion list to reject irrelevant titles like
    'Financial Analyst', 'Legal Counsel', 'Construction Project Manager'.
    """
    from app.services.role_classifier import _is_excluded
    if _is_excluded(title):
        return False
    return any(p.search(title) for p in COMPILED_ROLES)


def unescape_js_string(s: str) -> str:
    """Unescape a JavaScript string literal to recover the original string.

    Handles: \\\" → \", \\\\ → \\, \\n → newline, \\t → tab, \\/ → /
    This is needed for Apple's SSR hydration data which embeds JSON inside
    JSON.parse("...escaped...").
    """
    result = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            c = s[i + 1]
            if c == '\\':
                result.append('\\')
            elif c == '"':
                result.append('"')
            elif c == 'n':
                result.append('\n')
            elif c == 'r':
                result.append('\r')
            elif c == 't':
                result.append('\t')
            elif c == '/':
                result.append('/')
            elif c == 'b':
                result.append('\b')
            elif c == 'f':
                result.append('\f')
            else:
                result.append('\\')
                result.append(c)
            i += 2
        else:
            result.append(s[i])
            i += 1
    return ''.join(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Amazon — amazon.jobs/en/search.json
# ═══════════════════════════════════════════════════════════════════════════════

async def scrape_amazon(
    client: httpx.AsyncClient,
    search_terms: list[str] | None = None,
    location: str = "United States",
    max_results: int = 100,
) -> list[dict]:
    """Scrape Amazon jobs via their hidden JSON search API.

    Endpoint: https://www.amazon.jobs/en/search.json
    Params: base_query, loc_query, offset, result_limit, sort, category[]
    """
    if not search_terms:
        search_terms = ["Product Manager", "Program Manager", "UX Designer", "Software Engineer"]

    all_jobs = []

    for query in search_terms:
        offset = 0
        while offset < max_results:
            params = {
                "base_query": query,
                "offset": offset,
                "result_limit": 25,
                "sort": "recent",
            }
            if location:
                params["loc_query"] = location

            try:
                resp = await client.get(
                    "https://www.amazon.jobs/en/search.json",
                    params=params,
                    timeout=15,
                )
                if resp.status_code != 200:
                    break
                data = resp.json()
                hits = data.get("jobs", [])
                if not hits:
                    break

                for job in hits:
                    all_jobs.append({
                        "greenhouse_id": job.get("id_icims", job.get("id", "")),
                        "company": "amazon",
                        "title": job.get("title", ""),
                        "location": job.get("normalized_location", job.get("location", "")),
                        "department": job.get("job_category", ""),
                        "url": f"https://www.amazon.jobs{job.get('job_path', '')}",
                        "description": strip_html(job.get("description_short", "")),
                        "updated_at": job.get("posted_date", ""),
                        "first_published": job.get("posted_date", ""),
                        "employment_type": job.get("job_schedule_type", ""),
                        "salary_range": "",
                    })

                offset += 25
                if len(hits) < 25:
                    break
            except Exception:
                break

    # Deduplicate by job ID
    seen = set()
    unique = []
    for j in all_jobs:
        key = j["greenhouse_id"]
        if key not in seen:
            seen.add(key)
            unique.append(j)

    return unique


# ═══════════════════════════════════════════════════════════════════════════════
# Apple — jobs.apple.com (SSR hydration data extraction)
# ═══════════════════════════════════════════════════════════════════════════════

async def scrape_apple(
    client: httpx.AsyncClient,
    search_terms: list[str] | None = None,
    location: str = "united-states-USA",
    max_results: int = 100,
) -> list[dict]:
    """Scrape Apple jobs by extracting SSR hydration data from search pages.

    Apple embeds all search results in window.__staticRouterHydrationData.
    URL pattern: https://jobs.apple.com/en-us/search?search={query}&location={loc}&page={N}
    Returns 20 results per page.
    """
    if not search_terms:
        search_terms = ["Product Manager", "Program Manager", "UX Designer", "Software Engineer"]

    all_jobs = []
    seen_ids = set()

    for query in search_terms:
        page = 1
        while len(all_jobs) < max_results:
            try:
                params = {"search": query, "location": location, "page": page}
                resp = await client.get(
                    "https://jobs.apple.com/en-us/search",
                    params=params,
                    headers={**HEADERS, "Accept": "text/html"},
                    timeout=20,
                )
                if resp.status_code != 200:
                    break

                # Extract __staticRouterHydrationData from the page
                match = re.search(
                    r'window\.__staticRouterHydrationData\s*=\s*JSON\.parse\("(.*?)"\);',
                    resp.text, re.DOTALL
                )
                if not match:
                    break

                data = json.loads(unescape_js_string(match.group(1)))
                search_data = data.get("loaderData", {}).get("search", {})
                results = search_data.get("searchResults", [])
                total = search_data.get("totalRecords", 0)

                if not results:
                    break

                for job in results:
                    pid = str(job.get("positionId", job.get("id", "")))
                    if pid in seen_ids:
                        continue
                    seen_ids.add(pid)

                    locations = job.get("locations", [])
                    loc_str = " | ".join(
                        loc.get("name", "") for loc in locations
                        if isinstance(loc, dict)
                    )
                    team = job.get("team", {})
                    team_name = team.get("teamName", "") if isinstance(team, dict) else ""

                    all_jobs.append({
                        "greenhouse_id": pid,
                        "company": "apple",
                        "title": job.get("postingTitle", ""),
                        "location": loc_str,
                        "department": team_name,
                        "url": f"https://jobs.apple.com/en-us/details/{pid}",
                        "description": "",  # Not available in list view
                        "updated_at": job.get("postingDate", ""),
                        "first_published": job.get("postingDate", ""),
                        "employment_type": job.get("type", ""),
                        "salary_range": "",
                    })

                page += 1
                if page * 20 >= total or page > 10:  # Cap at 10 pages (200 jobs) per query
                    break
            except Exception:
                break

    return all_jobs[:max_results]


# ═══════════════════════════════════════════════════════════════════════════════
# Google — SSR HTML parsing from careers.google.com
# ═══════════════════════════════════════════════════════════════════════════════

async def scrape_google(
    client: httpx.AsyncClient,
    search_terms: list[str] | None = None,
    location: str = "United States",
    max_results: int = 100,
) -> list[dict]:
    """Scrape Google jobs from their careers page SSR HTML.

    Google embeds job card data in the initial HTML response:
      - Each card is a <li class="lLd3Je"> with ssk="N:JOB_ID"
      - Title in <h3> inside the card
      - Link as href="jobs/results/{ID}-{slug}"
      - Location as "City, ST, USA" text nearby

    Pagination: page=2, page=3, etc. ~20 results per page.
    """
    if not search_terms:
        search_terms = ["Product Manager", "Program Manager", "UX Designer"]

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    for query in search_terms:
        page = 1
        while len(all_jobs) < max_results:
            try:
                resp = await client.get(
                    "https://www.google.com/about/careers/applications/jobs/results",
                    params={"q": query, "location": location, "page": page},
                    headers={**HEADERS, "Accept": "text/html"},
                    timeout=20,
                )
                if resp.status_code != 200:
                    break

                html = resp.text

                # Split into job cards by <li class="lLd3Je">
                card_starts = [
                    m.start() for m in re.finditer(r'<li\s+class="lLd3Je"', html)
                ]
                if not card_starts:
                    break

                for i, start in enumerate(card_starts):
                    end = (
                        card_starts[i + 1]
                        if i + 1 < len(card_starts)
                        else html.find("</ul>", start)
                    )
                    card = html[start:end]

                    # Job ID from ssk attribute: ssk='17:80389585732805318'
                    ssk_m = re.search(r"ssk=['\"]?\d+:(\d+)", card)
                    job_id = ssk_m.group(1) if ssk_m else ""
                    if not job_id or job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    # Title from <h3>
                    h3_m = re.search(r"<h3[^>]*>(.*?)</h3>", card, re.DOTALL)
                    title = (
                        re.sub(r"<[^>]+>", "", h3_m.group(1)).strip()
                        if h3_m
                        else ""
                    )
                    if not title:
                        continue

                    # Link: href="jobs/results/{ID}-{slug}"
                    link_m = re.search(r'href="(jobs/results/[^"]+)"', card)
                    link_path = link_m.group(1) if link_m else ""

                    # Location: "City, ST, USA" pattern
                    loc_m = re.findall(
                        r">([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*"
                        r",\s*[A-Z]{2},?\s*USA?)<",
                        card,
                    )
                    location_str = loc_m[0] if loc_m else ""

                    url = (
                        f"https://www.google.com/about/careers/applications/{link_path}"
                        if link_path
                        else f"https://www.google.com/about/careers/applications/jobs/results/{job_id}"
                    )

                    all_jobs.append({
                        "greenhouse_id": f"google-{job_id}",
                        "company": "google",
                        "title": title,
                        "location": location_str,
                        "department": "",
                        "url": url,
                        "description": "",
                        "updated_at": "",
                        "first_published": "",
                        "employment_type": "",
                        "salary_range": "",
                    })

                # Fewer than ~15 cards → last page
                if len(card_starts) < 15:
                    break
                page += 1
                if page > 6:
                    break
            except Exception:
                break

    return all_jobs[:max_results]


# ═══════════════════════════════════════════════════════════════════════════════
# Meta — metacareers.com (requires browser session, limited httpx support)
# ═══════════════════════════════════════════════════════════════════════════════

async def scrape_meta(
    client: httpx.AsyncClient,
    search_terms: list[str] | None = None,
    max_results: int = 100,
) -> list[dict]:
    """Scrape Meta jobs from metacareers.com.

    Meta's careers page blocks non-browser HTTP clients (returns 400).
    This scraper attempts two strategies:
      1. JSON-LD structured data (if the page renders)
      2. HTML link parsing fallback
    If both fail (likely without browser cookies), returns empty list.
    Future: integrate Apify headless browser for reliable scraping.
    """
    if not search_terms:
        search_terms = ["Product Manager", "Program Manager", "UX Designer"]

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    for query in search_terms:
        try:
            resp = await client.get(
                "https://www.metacareers.com/jobs",
                params={"q": query},
                headers={**HEADERS, "Accept": "text/html,application/xhtml+xml"},
                timeout=20,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                print(f"[Meta] HTTP {resp.status_code} for query '{query}' — site blocks non-browser clients")
                continue

            html = resp.text

            # Strategy 1: JSON-LD structured data
            ld_blocks = re.findall(
                r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                html, re.DOTALL,
            )
            for ld_text in ld_blocks:
                try:
                    ld = json.loads(ld_text)
                    items = ld.get("itemListElement", []) if isinstance(ld, dict) else (ld if isinstance(ld, list) else [])
                    for item in items:
                        job = item.get("item", item) if isinstance(item, dict) else {}
                        jid = str(job.get("identifier", {}).get("value", ""))
                        if not jid or jid in seen_ids:
                            continue
                        seen_ids.add(jid)
                        jl = job.get("jobLocation", {})
                        loc = ""
                        if isinstance(jl, dict):
                            addr = jl.get("address", {})
                            if isinstance(addr, dict):
                                parts = [addr.get("addressLocality", ""), addr.get("addressRegion", "")]
                                loc = ", ".join(p for p in parts if p)
                        all_jobs.append({
                            "greenhouse_id": f"meta-{jid}",
                            "company": "meta",
                            "title": job.get("title", ""),
                            "location": loc,
                            "department": "",
                            "url": job.get("url", f"https://www.metacareers.com/jobs/{jid}"),
                            "description": strip_html(job.get("description", ""))[:500],
                            "updated_at": job.get("datePosted", ""),
                            "first_published": job.get("datePosted", ""),
                            "employment_type": job.get("employmentType", ""),
                            "salary_range": "",
                        })
                except (json.JSONDecodeError, TypeError):
                    pass

            # Strategy 2: job links from HTML
            job_links = re.findall(
                r'href="((?:https://www\.metacareers\.com)?/jobs/(\d+)/[^"]*)"',
                html,
            )
            for href, jid in job_links:
                if jid in seen_ids:
                    continue
                seen_ids.add(jid)
                pos = html.find(href)
                if pos < 0:
                    continue
                block = html[pos:pos + 500]
                title_m = re.search(r'>([^<]{5,100}(?:Manager|Engineer|Designer|Researcher|Analyst))<', block)
                if not title_m:
                    continue
                url = href if href.startswith("http") else f"https://www.metacareers.com{href}"
                all_jobs.append({
                    "greenhouse_id": f"meta-{jid}",
                    "company": "meta",
                    "title": title_m.group(1).strip(),
                    "location": "",
                    "department": "",
                    "url": url,
                    "description": "",
                    "updated_at": "",
                    "first_published": "",
                    "employment_type": "",
                    "salary_range": "",
                })

        except Exception:
            continue

    if not all_jobs:
        print("[Meta] No jobs scraped — metacareers.com requires browser session")

    return all_jobs[:max_results]


# ═══════════════════════════════════════════════════════════════════════════════
# Microsoft — apply.careers.microsoft.com PCSX JSON API
# ═══════════════════════════════════════════════════════════════════════════════

async def scrape_microsoft(
    client: httpx.AsyncClient,
    search_terms: list[str] | None = None,
    max_results: int = 100,
) -> list[dict]:
    """Scrape Microsoft jobs via their PCSX search API.

    Microsoft migrated to apply.careers.microsoft.com with a JSON API at
    /api/pcsx/search. Returns 10 positions per page, paginated via start=N.
    No auth required.
    """
    if not search_terms:
        search_terms = ["Product Manager", "Program Manager", "UX Designer"]

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    for query in search_terms:
        start = 0
        while len(all_jobs) < max_results:
            try:
                resp = await client.get(
                    "https://apply.careers.microsoft.com/api/pcsx/search",
                    params={
                        "domain": "microsoft.com",
                        "query": query,
                        "location": "United States",
                        "start": start,
                    },
                    headers={**HEADERS, "Accept": "application/json"},
                    timeout=20,
                )
                if resp.status_code != 200:
                    break

                data = resp.json()
                result = data.get("data", {})
                positions = result.get("positions", [])
                total = result.get("count", 0)

                if not positions:
                    break

                for pos in positions:
                    jid = str(pos.get("id", ""))
                    if not jid or jid in seen_ids:
                        continue
                    seen_ids.add(jid)

                    # Location: use standardizedLocations if available
                    std_locs = pos.get("standardizedLocations", [])
                    raw_locs = pos.get("locations", [])
                    location = (
                        " | ".join(std_locs[:3])
                        if std_locs
                        else " | ".join(raw_locs[:3])
                        if raw_locs
                        else ""
                    )

                    all_jobs.append({
                        "greenhouse_id": f"ms-{jid}",
                        "company": "microsoft",
                        "title": pos.get("name", ""),
                        "location": location,
                        "department": pos.get("department", ""),
                        "url": f"https://apply.careers.microsoft.com{pos.get('positionUrl', f'/careers/job/{jid}')}",
                        "description": "",
                        "updated_at": "",
                        "first_published": "",
                        "employment_type": pos.get("workLocationOption", ""),
                        "salary_range": "",
                    })

                start += len(positions)
                if start >= total:
                    break
            except Exception:
                break

    return all_jobs[:max_results]


# ═══════════════════════════════════════════════════════════════════════════════
# Unified entry point for all Big Tech scrapers
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# Netflix — Lever + Greenhouse
# ═══════════════════════════════════════════════════════════════════════════════

async def scrape_netflix(
    client: httpx.AsyncClient,
    search_terms: list[str] | None = None,
    max_results: int = 100,
) -> list[dict]:
    """Netflix posts on multiple platforms. Try Lever first, then look for jobs."""
    # Netflix often uses their own portal or Lever
    all_jobs = []
    try:
        resp = await client.get(
            "https://explore.jobs.netflix.net/api/apply/v2/jobs",
            params={"domain": "netflix.com", "start": 0, "num": min(50, max_results), "query": search_terms[0] if search_terms else ""},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            positions = data.get("positions", [])
            for job in positions:
                all_jobs.append({
                    "greenhouse_id": str(job.get("id", "")),
                    "company": "netflix",
                    "title": job.get("name", job.get("text", "")),
                    "location": job.get("location", ""),
                    "department": job.get("department", ""),
                    "url": job.get("canonicalPositionUrl", job.get("url", "")),
                    "description": strip_html(job.get("description", "")),
                    "updated_at": "",
                    "first_published": "",
                    "employment_type": "",
                    "salary_range": "",
                })
    except Exception:
        pass

    return all_jobs[:max_results]


# ═══════════════════════════════════════════════════════════════════════════════
# Scrapers that work via httpx (no browser needed)
# ═══════════════════════════════════════════════════════════════════════════════

BIGTECH_SCRAPERS = {
    "amazon": scrape_amazon,
    "apple": scrape_apple,
    "google": scrape_google,
    "meta": scrape_meta,
    "microsoft": scrape_microsoft,
    "netflix": scrape_netflix,
}

# Previously browser-only — now all use httpx with SSR/JSON parsing
BROWSER_ONLY_SCRAPERS: list[str] = []


async def scrape_bigtech(
    companies: list[str] | None = None,
    search_terms: list[str] | None = None,
    max_per_company: int = 50,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Scrape all Big Tech career pages.

    Args:
        companies: List of company names to scrape (default: all).
        search_terms: Search queries to use (default: PM/TPM/UX/SWE).
        max_per_company: Max jobs per company.
        progress_callback: Called with (done, total).

    Returns:
        Flat list of job dicts.
    """
    import ssl
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    targets = companies or list(BIGTECH_SCRAPERS.keys())
    valid_targets = [c for c in targets if c in BIGTECH_SCRAPERS]
    total = len(valid_targets)
    all_jobs = []

    async with httpx.AsyncClient(headers=HEADERS, verify=ssl_ctx, follow_redirects=True) as client:
        for i, company in enumerate(valid_targets):
            scraper_fn = BIGTECH_SCRAPERS[company]
            try:
                jobs = await scraper_fn(
                    client,
                    search_terms=search_terms,
                    max_results=max_per_company,
                )
                all_jobs.extend(jobs)
            except Exception as e:
                print(f"[BigTech] {company} scraper error: {e}")

            if progress_callback:
                progress_callback(i + 1, total)

    # Filter to US-only locations
    return [j for j in all_jobs if is_us_location(j.get("location", ""))]
