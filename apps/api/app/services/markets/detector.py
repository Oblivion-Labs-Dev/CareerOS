"""Career source detection: where does this company publish jobs, and how can they be read?

The ladder, cheapest first, each rung recorded in ``steps``:

0. a curated public board (known_sources.json) for sites that hide theirs;
   no career URL in the seed: probe ATS boards by name, then look for the
   company's own careers page (reference sheet, then careers.<domain> etc.,
   accepted only when the page names the company)
1. the official career URL itself (known ATS / proprietary portal by host)
2. fetch it: redirect target, ATS links/embeds in the HTML, JSON-LD JobPosting
3. probe the public ATS APIs by company name (Greenhouse, Lever, Ashby,
   SmartRecruiters), accepted only when the board verifiably belongs to the company
   (an ATS CareerOS cannot read yet is kept only if none of the above finds
   a readable board)
4. render it in a browser and watch the network for an ATS (only when allowed)
5. otherwise MANUAL / BLOCKED / UNKNOWN, with the reason

Fingerprinting is the existing ``JobSourceDiscoveryService.fingerprint_ats``;
this module adds the fetch, the ladder and the evidence trail. Aggregator
listing pages are never accepted as a company's career site.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.job_discover.discovery.company_registry import JobSourceDiscoveryService
from app.services.markets.identity import clean_name, name_key, slugify
from app.services.markets.sources import PROVIDERS, SourceType

logger = logging.getLogger("career_os.markets.detector")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Multi-employer listing sites. A company's career site is never one of these,
# unless the company *is* the site (Indeed's own careers page is official).
AGGREGATOR_HOSTS = (
    "indeed.com", "linkedin.com", "glassdoor.com", "ziprecruiter.com", "monster.com",
    "dice.com", "simplyhired.com", "builtin.com", "builtinseattle.com", "wellfound.com",
    "angel.co", "myvisajobs.com", "himalayas.app", "weworkremotely.com", "remoteok.com",
    "jobicy.com", "remotive.com", "careerbuilder.com", "lensa.com", "jooble.org",
)

_ATS_HOST_HINTS = (
    "greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "smartrecruiters.com",
    "workable.com", "recruitee.com", "personio.", "icims.com", "oraclecloud.com", "taleo.net",
    "jobvite.com", "successfactors.", "eightfold.ai", "phenompeople.com", "bamboohr.com",
    "breezy.hr", "teamtailor.com", "applytojob.com", "comeet.com", "pinpointhq.com",
    "rippling-ats.com", "amazon.jobs", "careers.microsoft.com", "metacareers.com", "jobs.apple.com",
)
_URL_IN_TEXT = re.compile(r"https?:(?:\\?/){2}[^\s\"'<>()\\]+", re.I)
_LOCALE = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?$", re.I)
_NOT_ICIMS_PORTALS = {"www", "cdn", "static", "assets", "images", "developer", "community"}
_ORACLE_SITE = re.compile(r"siteNumber=(CX_\d+)")


@dataclass
class Detection:
    source_type: str = SourceType.UNKNOWN.value
    provider: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    method: str = "none"
    confidence: float = 0.0
    evidence: str = ""
    career_url: str = ""
    url_source: str = ""
    http_status: int | None = None
    final_url: str = ""
    failure_reason: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)

    def note(self, step: str, outcome: str, **detail: Any) -> None:
        self.steps.append({"step": step, "outcome": outcome, **{k: v for k, v in detail.items() if v not in (None, "")}})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@lru_cache(maxsize=1)
def known_sources() -> dict[str, dict[str, str]]:
    """Curated public boards (known_sources.json), keyed by company name_key."""
    data = json.loads((Path(__file__).with_name("known_sources.json")).read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def host_of(url: str) -> str:
    try:
        return (urlparse(url or "").netloc or "").lower().split(":")[0]
    except ValueError:  # malformed URLs scraped from page HTML, e.g. "http://[x"
        return ""


def is_aggregator_for(url: str, company_name: str) -> bool:
    """True when ``url`` is a multi-employer listing site that is not the company's own."""
    host = host_of(url)
    for agg in AGGREGATOR_HOSTS:
        if host == agg or host.endswith("." + agg):
            brand = agg.split(".")[0]
            return name_key(company_name) != brand
    return False


def _workday_config(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    parts = [p for p in parsed.path.split("/") if p]
    while parts and _LOCALE.match(parts[0]):
        parts.pop(0)
    board = parts[0] if parts else "careers"
    return {"host": host, "tenant": host.split(".")[0], "company": host.split(".")[0], "board": board}


def provider_from_url(url: str, html: str | None = None) -> tuple[str | None, dict[str, Any], float, str]:
    """(provider id, adapter config, confidence, evidence) for a URL (and optionally its HTML)."""
    fp = JobSourceDiscoveryService.fingerprint_ats(url, html)
    provider = fp.get("provider") or ""
    board = fp.get("boardIdentifier") or ""
    confidence = float(fp.get("confidence") or 0)
    evidence = fp.get("evidence") or ""
    if provider == "bigtech":
        return board, {}, confidence, evidence
    if provider == "workday":
        if "myworkdayjobs.com" in host_of(url):
            return "workday", _workday_config(url), confidence, evidence
        host, _, site = board.partition("/")
        return "workday", {"host": host, "tenant": host.split(".")[0], "company": host.split(".")[0], "board": site or "careers"}, confidence, evidence
    if provider == "icims":
        portal = host_of(url).split(".")[0]
        if portal in _NOT_ICIMS_PORTALS:
            return None, {}, 0.0, "iCIMS marketing or CDN link, not a job portal"
        return "icims", {"portal": portal}, confidence, evidence
    if provider == "oracle":
        host = host_of(url)
        site_number = _ORACLE_SITE.search(f"{url} {html or ''}")
        site = site_number.group(1) if site_number else board.rpartition(":")[2]
        return "oracle", {"host": host, "site": site or "jobsearch"}, confidence, evidence
    if provider == "structured_career_page":
        if confidence >= 0.85:
            return "jsonld", {"careersUrl": url}, confidence, evidence
        return None, {}, confidence, evidence
    if provider in PROVIDERS:
        if not board or board in ("embed", "job_board", "v1", "jobs"):
            return None, {}, 0.0, f"{provider} detected but no board identifier"
        return provider, {"slug": board}, confidence, evidence
    return None, {}, confidence, evidence


def ats_urls_in(text: str) -> list[str]:
    """Absolute URLs in page text/HTML that point at a known ATS or portal."""
    seen: list[str] = []
    for raw in _URL_IN_TEXT.findall(text or ""):
        url = raw.replace("\\/", "/").rstrip(".,;")
        host = host_of(url)
        if any(hint in host for hint in _ATS_HOST_HINTS) and url not in seen:
            seen.append(url)
    return seen


def best_provider(urls: list[str]) -> tuple[str | None, dict[str, Any], float, str, str]:
    """Most useful provider among candidate URLs: supported adapters first, then by confidence."""
    best: tuple[str | None, dict[str, Any], float, str, str] = (None, {}, 0.0, "", "")
    best_rank = (-1, -1.0)
    for url in urls:
        provider, config, confidence, evidence = provider_from_url(url)
        if not provider:
            continue
        rank = (1 if PROVIDERS.get(provider) and PROVIDERS[provider].supported else 0, confidence)
        if rank > best_rank:
            best_rank = rank
            best = (provider, config, confidence, evidence, url)
    return best


def _apply(detection: Detection, provider: str, config: dict[str, Any], confidence: float, method: str, evidence: str) -> Detection:
    spec = PROVIDERS.get(provider)
    detection.provider = provider
    detection.config = config
    detection.confidence = round(confidence, 2)
    detection.method = method
    detection.evidence = evidence
    detection.source_type = spec.source_type.value if spec else SourceType.UNKNOWN.value
    if spec and not spec.supported:
        detection.failure_reason = f"{spec.label} detected; no unattended reader for it yet"
    return detection


# ── ATS probing by company name ─────────────────────────────────────────────


def slug_candidates(name: str) -> list[tuple[str, bool]]:
    """(slug, strict) pairs. A strict slug is a guess that is only accepted when
    the board's own name is the whole company name, not merely a prefix of it."""
    key = name_key(name)
    words = clean_name(name).split()
    out: list[tuple[str, bool]] = []
    for slug, strict in ((key, False), (slugify(name), False), (f"{key}usa", False), (words[0] if len(words) > 1 else "", True)):
        if slug and len(slug) >= 3 and slug not in {s for s, _ in out}:
            out.append((slug, strict))
    return out


def _mentions(text: str, name: str) -> bool:
    words = clean_name(name)
    return bool(words) and re.search(rf"\b{re.escape(words)}\b", clean_name(text or "")) is not None


async def _get_json(client: httpx.AsyncClient, url: str, **kwargs: Any) -> tuple[int | None, Any]:
    try:
        resp = await client.get(url, timeout=12.0, **kwargs)
    except (httpx.HTTPError, TimeoutError) as exc:
        logger.debug("probe %s failed: %s", url, exc)
        return None, None
    if resp.status_code != 200:
        return resp.status_code, None
    try:
        return 200, resp.json()
    except ValueError:
        return 200, None


async def probe_ats(client: httpx.AsyncClient, name: str) -> tuple[str, dict[str, Any], float, str, str] | None:
    """Find a public ATS board that verifiably belongs to ``name``.

    Returns (provider, config, confidence, evidence, board_url). Greenhouse and
    SmartRecruiters return the employer name, so a match is checked directly.
    Lever and Ashby do not; there a board is accepted only when its postings
    name the company.
    """
    key = name_key(name)
    for slug, strict in slug_candidates(name):
        status, data = await _get_json(client, f"https://boards-api.greenhouse.io/v1/boards/{slug}")
        if status == 200 and isinstance(data, dict):
            board_key = name_key(str(data.get("name") or ""))
            if board_key and (board_key == key or (not strict and (board_key.startswith(key) or key.startswith(board_key)))):
                return ("greenhouse", {"slug": slug}, 0.9,
                        f"Greenhouse board '{slug}' is named '{data.get('name')}'",
                        f"https://job-boards.greenhouse.io/{slug}")

        status, data = await _get_json(client, f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json", "limit": 5})
        if status == 200 and isinstance(data, list) and data:
            if any(_mentions(" ".join(str(p.get(k) or "") for k in ("descriptionPlain", "additionalPlain", "text")), name) for p in data):
                return ("lever", {"slug": slug}, 0.85, f"Lever board '{slug}' postings name the company",
                        f"https://jobs.lever.co/{slug}")

        status, data = await _get_json(client, f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        if status == 200 and isinstance(data, dict) and data.get("jobs"):
            jobs = data["jobs"][:5]
            if any(_mentions(" ".join(str(j.get(k) or "") for k in ("descriptionPlain", "title")), name) for j in jobs):
                return ("ashby", {"slug": slug}, 0.85, f"Ashby board '{slug}' postings name the company",
                        f"https://jobs.ashbyhq.com/{slug}")

        status, data = await _get_json(client, f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params={"limit": 5})
        if status == 200 and isinstance(data, dict) and data.get("content"):
            company_names = {name_key(str((p.get("company") or {}).get("name") or "")) for p in data["content"]}
            if key in company_names or (not strict and any(n.startswith(key) for n in company_names if n)):
                return ("smartrecruiters", {"slug": slug}, 0.9, f"SmartRecruiters company '{slug}' postings are by {name}",
                        f"https://jobs.smartrecruiters.com/{slug}")
    return None


async def _jibe_config(client: httpx.AsyncClient, page_url: str, html: str) -> dict[str, Any] | None:
    """iCIMS Jibe career sites (careers.<company>.com/careers-home) serve their jobs at /api/jobs."""
    if "jibecdn.com" not in html:
        return None
    parsed = urlparse(page_url)
    status, data = await _get_json(client, f"{parsed.scheme or 'https'}://{parsed.netloc}/api/jobs", params={"page": 1, "limit": 1})
    if status != 200 or not isinstance(data, dict) or "jobs" not in data:
        return None
    jobs_path = "/careers-home/jobs" if "/careers-home" in parsed.path else "/jobs"
    return {"host": parsed.netloc, "jobsPath": jobs_path}


# ── Finding a career URL the seed did not have ──────────────────────────────

_CAREER_WORDS = re.compile(r"\b(careers?|jobs?|openings|positions|join us|work with us)\b", re.I)


def _domains(name: str) -> list[str]:
    """Plausible company-owned domains: 'Bill.com' -> bill.com, 'AT&T' -> att.com, 'Glean' -> glean.com."""
    lowered = (name or "").strip().lower()
    if re.fullmatch(r"[a-z0-9-]+\.(com|ai|io|org|net|co)", lowered):
        return [lowered]
    bases: list[str] = []
    for base in (re.sub(r"[^a-z0-9]", "", lowered), name_key(name)):
        if len(base) >= 3 and base not in bases:
            bases.append(base)
    domains = [f"{b}.com" for b in bases]
    domains += [f"{b}.ai" for b in bases if b.endswith("ai")]
    return domains


async def _career_page(client: httpx.AsyncClient, url: str, domain: str, name: str) -> tuple[str, str] | None:
    """(final url, evidence) when ``url`` is verifiably this company's career page."""
    try:
        resp = await client.get(url, headers=BROWSER_HEADERS, timeout=10.0, follow_redirects=True)
    except (httpx.HTTPError, TimeoutError):
        return None
    final = str(resp.url)
    if resp.status_code != 200 or is_aggregator_for(final, name):
        return None
    provider, *_ = provider_from_url(final)
    if provider:
        return final, f"{url} redirects to the {provider} board {final}"
    host = host_of(final)
    if not (host == domain or host.endswith("." + domain)):
        return None
    html = resp.text or ""
    if _mentions(html[:400_000], name) and _CAREER_WORDS.search(html[:400_000]):
        return final, f"{url} is a careers page on {domain} that names {name}"
    return None


async def find_career_url(client: httpx.AsyncClient, company: dict[str, Any]) -> tuple[str, str, str] | None:
    """(url, url_source, evidence) for a company whose seed row had no career URL."""
    name = company.get("name", "")
    for alt in (company.get("career") or {}).get("alternateUrls") or []:
        url = alt.get("url") if isinstance(alt, dict) else alt
        if url and not is_aggregator_for(url, name):
            return url, "reference_sheet", "Listed as the company's careers page in the seed's reference sheet"
    candidates = [
        (url, domain)
        for domain in _domains(name)
        for url in (f"https://careers.{domain}", f"https://www.{domain}/careers", f"https://jobs.{domain}")
    ]
    results = await asyncio.gather(*(_career_page(client, url, domain, name) for url, domain in candidates))
    for found in results:
        if found:
            return found[0], "domain_verified", found[1]
    return None


# ── Browser rung ────────────────────────────────────────────────────────────


class BrowserProbe:
    """One headless Chromium shared by a refresh run; each probe gets its own context."""

    def __init__(self, timeout_ms: int = 25000, max_pages: int = 2) -> None:
        self.timeout_ms = timeout_ms
        self._playwright: Any = None
        self._browser: Any = None
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(max_pages)
        self.unavailable_reason = ""

    async def _ensure(self) -> bool:
        async with self._lock:
            if self._browser is not None:
                return True
            if self.unavailable_reason:
                return False
            try:
                from playwright.async_api import async_playwright

                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)
                return True
            except Exception as exc:  # missing browsers, sandbox, etc.
                self.unavailable_reason = f"Browser unavailable: {exc}"
                return False

    async def inspect(self, url: str) -> dict[str, Any]:
        if not await self._ensure():
            return {"ok": False, "error": self.unavailable_reason}
        async with self._slots:
            return await self._inspect(url)

    async def _inspect(self, url: str) -> dict[str, Any]:
        context = await self._browser.new_context(user_agent=BROWSER_HEADERS["User-Agent"])
        requests: list[str] = []
        page = await context.new_page()
        page.on("request", lambda req: requests.append(req.url))
        status = None
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            status = response.status if response else None
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            html = await page.content()
            frames = [f.url for f in page.frames if f.url and f.url != "about:blank"]
            return {"ok": True, "status": status, "finalUrl": page.url, "html": html, "requests": requests + frames}
        except Exception as exc:
            return {"ok": False, "status": status, "error": f"Browser load failed: {str(exc).splitlines()[0][:200]}", "requests": requests}
        finally:
            await context.close()

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None


# ── The ladder ──────────────────────────────────────────────────────────────


async def detect(
    client: httpx.AsyncClient,
    company: dict[str, Any],
    *,
    browser: BrowserProbe | None = None,
) -> Detection:
    name = company.get("name", "")
    career = company.get("career") or {}
    url = (career.get("url") or "").strip()
    det = Detection(career_url=url, url_source=career.get("urlSource") or "")

    if company.get("kind") == "ecosystem":
        det.source_type = SourceType.MANUAL.value
        det.method = "not_an_employer"
        det.failure_reason = "Ecosystem placeholder, not a single employer — browse its companies individually"
        det.note("identity", "skipped", reason=det.failure_reason)
        return det

    if url and is_aggregator_for(url, name):
        det.note("career_url", "rejected", url=url, reason="Aggregator listing page, not the company's career site")
        url = ""
        det.career_url = ""

    known = known_sources().get(name_key(name))
    if known:
        provider, config, _confidence, _evidence = provider_from_url(known["url"])
        if provider:
            det.note("known_source", "matched", board=known["url"], verified=known.get("verified"))
            if not url:
                det.career_url = known["url"]
                det.url_source = "known_source"
            return _apply(det, provider, config, 0.95, "known_source", known.get("evidence") or f"Curated board {known['url']}")

    probed_by_name = False
    if not url:
        probed = await probe_ats(client, name)
        probed_by_name = True
        if probed:
            provider, config, confidence, evidence, board_url = probed
            det.note("ats_probe", "matched", provider=provider, board=board_url)
            det.career_url = board_url
            det.url_source = "ats_probe"
            return _apply(det, provider, config, confidence, "ats_probe", evidence)
        det.note("ats_probe", "no_verified_board")
        found = await find_career_url(client, company)
        if found:
            url, det.url_source, evidence = found
            det.career_url = url
            det.note("career_url", "found", url=url, source=det.url_source, evidence=evidence)
        else:
            det.note("career_url", "not_found", tried=", ".join(_domains(name)))

    # A recognised ATS without a reader is remembered, not returned: the
    # company may also run a public board CareerOS can read (Twilio's page
    # links Eightfold; its jobs are on Greenhouse).
    unreadable: tuple[str, dict[str, Any], float, str, str] | None = None

    def readable(provider: str, config: dict[str, Any], confidence: float, method: str, evidence: str) -> bool:
        nonlocal unreadable
        spec = PROVIDERS.get(provider)
        if spec and spec.supported:
            return True
        unreadable = unreadable or (provider, config, confidence, method, evidence)
        return False

    # 1. The URL alone.
    if url:
        provider, config, confidence, evidence = provider_from_url(url)
        if provider:
            det.note("url_fingerprint", "matched", provider=provider, evidence=evidence)
            if readable(provider, config, confidence, "url_fingerprint", evidence):
                return _apply(det, provider, config, confidence, "url_fingerprint", evidence)
        else:
            det.note("url_fingerprint", "no_match", url=url)

    # 2. Fetch the page.
    html = ""
    blocked = False
    if url:
        try:
            resp = await client.get(url, headers=BROWSER_HEADERS, timeout=15.0, follow_redirects=True)
            det.http_status = resp.status_code
            det.final_url = str(resp.url)
            det.note("fetch", f"HTTP {resp.status_code}", finalUrl=det.final_url if det.final_url != url else None)
            if det.final_url and det.final_url != url and not is_aggregator_for(det.final_url, name):
                provider, config, confidence, evidence = provider_from_url(det.final_url)
                if provider:
                    det.note("redirect_fingerprint", "matched", provider=provider)
                    evidence = f"Career URL redirects to {det.final_url}"
                    if readable(provider, config, confidence, "redirect", evidence):
                        return _apply(det, provider, config, confidence, "redirect", evidence)
            if resp.status_code in (401, 403, 429, 503):
                blocked = True
                det.failure_reason = f"HTTP {resp.status_code} to a non-browser client"
            elif resp.status_code >= 400:
                det.failure_reason = f"Career URL returned HTTP {resp.status_code}"
            else:
                html = resp.text or ""
        except (httpx.HTTPError, TimeoutError) as exc:
            det.failure_reason = f"Career URL unreachable: {type(exc).__name__}"
            det.note("fetch", "error", error=str(exc)[:200])

    if html:
        jibe = await _jibe_config(client, det.final_url or url, html)
        if jibe:
            det.note("jibe_api", "matched", host=jibe["host"])
            return _apply(det, "jibe", jibe, 0.95, "json_api", f"https://{jibe['host']}/api/jobs answers with the job list")
        provider, config, confidence, evidence, link = best_provider(ats_urls_in(html))
        if provider == "oracle" and (site_number := _ORACLE_SITE.search(html)):
            config = {**config, "site": site_number.group(1)}
        if provider:
            det.note("html_links", "matched", provider=provider, link=link)
            if readable(provider, config, min(confidence, 0.92), "html_embed", f"Career page links to {link}"):
                return _apply(det, provider, config, min(confidence, 0.92), "html_embed", f"Career page links to {link}")
        else:
            provider, config, confidence, evidence = provider_from_url(det.final_url or url, html)
            if provider:
                det.note("html_fingerprint", "matched", provider=provider, evidence=evidence)
                method = "jsonld" if provider == "jsonld" else "html_embed"
                if readable(provider, config, confidence, method, evidence):
                    return _apply(det, provider, config, confidence, method, evidence)
            else:
                det.note("html_inspection", "no_ats_or_jsonld", bytes=len(html))

    # 3. Public ATS boards under the company's name.
    if not probed_by_name:
        probed = await probe_ats(client, name)
        if probed:
            provider, config, confidence, evidence, board_url = probed
            det.note("ats_probe", "matched", provider=provider, board=board_url)
            return _apply(det, provider, config, confidence, "ats_probe", evidence)
        det.note("ats_probe", "no_verified_board")

    if unreadable:
        return _apply(det, *unreadable)

    # 4. Browser render: what does the page load?
    if url and browser is not None:
        seen = await browser.inspect(url)
        if seen.get("ok"):
            candidates = ats_urls_in("\n".join(seen.get("requests") or [])) + ats_urls_in(seen.get("html") or "")
            provider, config, confidence, evidence, link = best_provider(candidates)
            if provider:
                det.note("browser", "matched", provider=provider, link=link)
                return _apply(det, provider, config, min(confidence, 0.85), "browser_network", f"Rendered page requests {link}")
            provider, config, confidence, evidence = provider_from_url(seen.get("finalUrl") or url, seen.get("html") or "")
            if provider == "jsonld":
                det.note("browser", "jsonld")
                det.source_type = SourceType.BROWSER.value
                det.provider = None
                det.method = "browser_jsonld"
                det.failure_reason = "Job data only appears after JavaScript renders"
                return det
            det.note("browser", "no_ats", status=seen.get("status"))
            blocked = blocked and (seen.get("status") or 0) in (401, 403, 429)
            if not det.failure_reason or not blocked:
                det.failure_reason = "JavaScript career site with no detectable ATS or job feed"
        else:
            det.note("browser", "failed", error=seen.get("error"))

    # 5. Nothing CareerOS can read unattended.
    if not url:
        det.source_type = SourceType.UNKNOWN.value
        det.failure_reason = det.failure_reason or "No official career URL; no public ATS board found under the company name"
    elif blocked:
        det.source_type = SourceType.BLOCKED.value
    else:
        det.source_type = SourceType.MANUAL.value
        det.failure_reason = det.failure_reason or "Career site has no ATS, feed or structured data CareerOS can read"
    det.method = "fallback"
    return det
