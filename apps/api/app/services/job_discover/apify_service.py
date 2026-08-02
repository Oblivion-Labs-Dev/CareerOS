"""JobPilot — Apify integration for LinkedIn/Indeed/Glassdoor jobs.

Uses Apify's API to run pre-built Actors for scraping job boards
that block direct API access (LinkedIn, Indeed, Glassdoor, etc.).

Setup:
  1. Get your Apify API token from https://console.apify.com/account/integrations
  2. Set it in data/apify_config.yaml or as APIFY_TOKEN env var
  3. Call scrape_via_apify() with your search parameters

Recommended Actors:
  - "bebity/linkedin-jobs-scraper"  — LinkedIn job search
  - "misceres/indeed-scraper"       — Indeed job search
  - "epctex/glassdoor-scraper"      — Glassdoor job search
"""

import asyncio
import os
import re
from pathlib import Path

import httpx
import yaml

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
    """Check if a location string appears to be in the United States."""
    if not location or not location.strip():
        return True
    loc = location.strip()
    if _US_PAT.search(loc):
        return True
    if _STATE_NAMES_PAT.search(loc):
        return True
    parts = [p.strip() for p in loc.replace("|", ",").split(",")]
    for part in parts:
        if part.upper() in US_STATES_ABBR:
            return True
    if re.search(r"\bremote\b", loc, re.IGNORECASE) and not _FOREIGN_PAT.search(loc):
        return True
    if _FOREIGN_PAT.search(loc):
        return False
    return True

CONFIG_FILE = Path(__file__).resolve().parents[3] / "data" / "job_discover" / "apify_config.yaml"
APIFY_BASE = "https://api.apify.com/v2"


def load_apify_config() -> dict:
    """Load Apify token and actor configs from apify_config.yaml or env."""
    from app.config import settings

    config = {"token": os.environ.get("APIFY_TOKEN", "") or settings.apify_token, "actors": {}}

    if CONFIG_FILE.exists():
        try:
            raw = yaml.safe_load(CONFIG_FILE.read_text()) or {}
            # Only use YAML token if it's a real token (not the placeholder)
            yaml_token = raw.get("token", "")
            if yaml_token and "YOUR_TOKEN_HERE" not in yaml_token:
                config["token"] = yaml_token
            config["actors"] = raw.get("actors", {})
        except Exception:
            pass

    return config


def strip_html(html: str) -> str:
    if not html:
        return ""
    from html import unescape
    text = unescape(html)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ── LinkedIn Actor ───────────────────────────────────────────────────────────

def build_linkedin_input(
    search_terms: list[str],
    location: str = "United States",
    max_results: int = 100,
) -> dict:
    """Build input JSON for curious_coder~linkedin-jobs-scraper.

    This actor takes LinkedIn search URLs directly (not raw keywords).
    URL params:
      keywords  — search term
      location  — location filter
      f_TPR     — time posted (r604800 = past week)
      f_E       — experience level (2=Entry, 3=Associate, 4=Mid-Senior)
    """
    from urllib.parse import quote_plus

    urls = []
    for term in search_terms:
        url = (
            f"https://www.linkedin.com/jobs/search/"
            f"?keywords={quote_plus(term)}"
            f"&location={quote_plus(location)}"
            f"&f_TPR=r604800"
            f"&f_E=2%2C3%2C4"
        )
        urls.append(url)

    return {
        "urls": urls,
        "scrapeCompany": False,   # Skip extra requests per job — faster
        "count": max_results,
    }


def flatten_linkedin_job(item: dict) -> dict:
    """Normalize a LinkedIn Actor result to our standard job format.

    Expected JSON from the Apify actor:
      { "id", "title", "company", "location", "employmentType",
        "seniorityLevel", "salary", "applicantsCount",
        "postedAt", "jobUrl", "description" }
    """
    seniority = item.get("seniorityLevel", "")
    applicants = item.get("applicantsCount", "")
    dept = seniority  # Use seniority as department (LinkedIn has no dept field)

    desc = strip_html(item.get("description", ""))[:500]
    if applicants:
        desc = f"[{applicants} applicants] {desc}"

    return {
        "greenhouse_id": str(item.get("id", item.get("jobId", ""))),
        "company": item.get("company", item.get("companyName", "")),
        "title": item.get("title", item.get("jobTitle", "")),
        "location": item.get("location", item.get("formattedLocation", "")),
        "department": dept,
        "url": item.get("jobUrl", item.get("url", item.get("link", ""))),
        "description": desc,
        "updated_at": item.get("postedAt", item.get("publishedAt", "")),
        "first_published": item.get("postedAt", ""),
        "employment_type": item.get("employmentType", item.get("workType", "")),
        "salary_range": item.get("salary", item.get("salaryInfo", "")),
    }


# ── Indeed Actor ─────────────────────────────────────────────────────────────

def build_indeed_input(
    search_terms: list[str],
    location: str = "United States",
    max_results: int = 100,
) -> dict:
    return {
        "queries": [{"query": q, "location": location} for q in search_terms],
        "maxResults": max_results,
        "publishedAt": "last 7 days",
        "proxy": {"useApifyProxy": True},
    }


def flatten_indeed_job(item: dict) -> dict:
    return {
        "greenhouse_id": str(item.get("id", item.get("jobKey", ""))),
        "company": item.get("company", item.get("companyName", "")),
        "title": item.get("title", item.get("jobTitle", "")),
        "location": item.get("location", ""),
        "department": "",
        "url": item.get("url", item.get("jobUrl", "")),
        "description": strip_html(item.get("description", ""))[:500],
        "updated_at": item.get("postedAt", ""),
        "first_published": item.get("postedAt", ""),
        "employment_type": item.get("jobType", ""),
        "salary_range": item.get("salary", ""),
    }


# ── Generic Apify Actor Runner ──────────────────────────────────────────────

async def run_apify_actor(
    actor_id: str,
    input_data: dict,
    token: str,
    timeout_secs: int = 300,
) -> list[dict]:
    """Run an Apify Actor and wait for results.

    Args:
        actor_id: e.g. "bebity/linkedin-jobs-scraper"
        input_data: JSON input for the actor
        token: Apify API token
        timeout_secs: Max seconds to wait for the run to finish

    Returns:
        List of result items from the actor's dataset.
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        # Start the actor run
        resp = await client.post(
            f"{APIFY_BASE}/acts/{actor_id}/runs",
            json=input_data,
            headers=headers,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Apify start failed: {resp.status_code} {resp.text[:200]}")

        run_data = resp.json().get("data", {})
        run_id = run_data.get("id")
        if not run_id:
            raise RuntimeError("No run ID returned")

        # Poll until finished
        elapsed = 0
        poll_interval = 5
        while elapsed < timeout_secs:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            resp = await client.get(
                f"{APIFY_BASE}/actor-runs/{run_id}",
                headers=headers,
            )
            if resp.status_code != 200:
                continue

            status = resp.json().get("data", {}).get("status")
            if status == "SUCCEEDED":
                break
            elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
                raise RuntimeError(f"Apify run {status}")

        # Fetch results from the dataset
        dataset_id = run_data.get("defaultDatasetId")
        if not dataset_id:
            return []

        resp = await client.get(
            f"{APIFY_BASE}/datasets/{dataset_id}/items",
            params={"format": "json", "limit": 500},
            headers=headers,
        )
        if resp.status_code != 200:
            return []

        return resp.json()


# ── High-Level Scrape Functions ──────────────────────────────────────────────

async def scrape_linkedin_via_apify(
    search_terms: list[str],
    location: str = "United States",
    max_results: int = 100,
) -> list[dict]:
    """Scrape LinkedIn jobs via Apify Actor.

    Requires APIFY_TOKEN in env or data/apify_config.yaml.
    """
    config = load_apify_config()
    token = config["token"]
    if not token:
        raise RuntimeError(
            "No Apify token. Set APIFY_TOKEN env var or add 'token:' to data/apify_config.yaml"
        )

    actor_id = config.get("actors", {}).get("linkedin", "bebity/linkedin-jobs-scraper")
    input_data = build_linkedin_input(search_terms, location, max_results)

    results = await run_apify_actor(actor_id, input_data, token)
    jobs = [flatten_linkedin_job(item) for item in results]
    return [j for j in jobs if is_us_location(j.get("location", ""))]


async def scrape_indeed_via_apify(
    search_terms: list[str],
    location: str = "United States",
    max_results: int = 100,
) -> list[dict]:
    """Scrape Indeed jobs via Apify Actor."""
    config = load_apify_config()
    token = config["token"]
    if not token:
        raise RuntimeError("No Apify token configured")

    actor_id = config.get("actors", {}).get("indeed", "misceres/indeed-scraper")
    input_data = build_indeed_input(search_terms, location, max_results)

    results = await run_apify_actor(actor_id, input_data, token)
    jobs = [flatten_indeed_job(item) for item in results]
    return [j for j in jobs if is_us_location(j.get("location", ""))]


async def scrape_via_apify(
    platform: str = "linkedin",
    search_terms: list[str] | None = None,
    location: str = "United States",
    max_results: int = 100,
) -> list[dict]:
    """Unified entry point for all Apify-based scrapers.

    Args:
        platform: "linkedin", "indeed", or a custom actor ID
        search_terms: What to search for
        location: Location filter
        max_results: Max results

    Returns:
        List of normalized job dicts.
    """
    if not search_terms:
        search_terms = ["Product Manager", "Program Manager", "UX Designer"]

    if platform == "linkedin":
        return await scrape_linkedin_via_apify(search_terms, location, max_results)
    elif platform == "indeed":
        return await scrape_indeed_via_apify(search_terms, location, max_results)
    else:
        # Custom actor — run directly
        config = load_apify_config()
        token = config["token"]
        if not token:
            raise RuntimeError("No Apify token configured")
        results = await run_apify_actor(platform, {"queries": search_terms}, token)
        return results


# ── Company-Targeted LinkedIn Searches ─────────────────────────────────────
# Companies that don't have public ATS APIs and need LinkedIn scraping.

APIFY_TARGET_COMPANIES: list[str] = [
    # Companies without public ATS APIs — need LinkedIn scraping
    "Meta", "Uber", "DoorDash", "Adobe", "Cisco",
    "ServiceNow", "PayPal", "Intuit", "Snap Inc", "TikTok",
    "ByteDance", "IBM", "Oracle", "Accenture", "Walmart",
    "Expedia", "eBay", "Mastercard", "Capital One", "Booking.com",
    # Companies with empty/small ATS boards — supplement via LinkedIn
    "Coinbase", "Rippling", "Dell Technologies", "Disney",
    "LinkedIn",
]

APIFY_ROLE_QUERIES: list[str] = [
    "Product Manager",
    "Program Manager",
    "Software Engineer",
    "UX Designer",
]


def build_company_linkedin_urls(
    companies: list[str],
    roles: list[str],
    location: str = "United States",
) -> list[str]:
    """Build LinkedIn search URLs for specific companies + roles.

    Uses 'Company Product Manager' as the keyword to target jobs at that company.
    """
    from urllib.parse import quote_plus

    urls = []
    for company in companies:
        for role in roles:
            keyword = f"{company} {role}"
            url = (
                f"https://www.linkedin.com/jobs/search/"
                f"?keywords={quote_plus(keyword)}"
                f"&location={quote_plus(location)}"
                f"&f_TPR=r604800"
                f"&f_E=2%2C3%2C4"
            )
            urls.append(url)
    return urls


async def scrape_company_linkedin_jobs(
    companies: list[str] | None = None,
    roles: list[str] | None = None,
    location: str = "United States",
    max_results: int = 200,
) -> list[dict]:
    """Scrape LinkedIn for jobs at specific companies we can't reach via ATS APIs.

    This targets companies like Meta, Uber, Adobe etc. that block direct API access.
    Runs one Apify actor call with all company+role URL combinations.
    """
    config = load_apify_config()
    token = config["token"]
    if not token:
        return []

    target_companies = companies or APIFY_TARGET_COMPANIES
    target_roles = roles or APIFY_ROLE_QUERIES
    actor_id = config.get("actors", {}).get("linkedin", "bebity/linkedin-jobs-scraper")

    urls = build_company_linkedin_urls(target_companies, target_roles, location)

    input_data = {
        "urls": urls,
        "scrapeCompany": False,
        "count": max_results,
    }

    try:
        results = await run_apify_actor(actor_id, input_data, token, timeout_secs=600)
        jobs = [flatten_linkedin_job(item) for item in results]
        return [j for j in jobs if is_us_location(j.get("location", ""))]
    except Exception as e:
        import logging
        logging.getLogger("jobpilot").error(f"Company LinkedIn scrape failed: {e}")
        return []
