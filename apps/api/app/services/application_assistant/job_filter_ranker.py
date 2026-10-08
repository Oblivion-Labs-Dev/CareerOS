"""Deterministic hard filter & AI ranking engine for Autopilot jobs."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.services.application_assistant.domain import AutopilotJobStatus
from app.services.application_assistant.persistence import list_autopilot_jobs


DEFAULT_MIN_MATCH_SCORE = 75.0
DEFAULT_MAX_POST_AGE_DAYS = 30  # Only apply to jobs posted within the last 30 days
DEFAULT_MAX_APPLICATIONS_PER_RUN = 25

# IC-level AI/ML engineering titles to treat as SWE-eligible and prioritize
# alongside plain "software engineer" roles. Deliberately excludes anything
# that is a leadership/executive variant (Chief AI Officer, VP, Director,
# Head of, ...) — those are already dropped everywhere by management_keywords
# / management_markers regardless of an "AI" prefix.
AI_ML_TITLE_KEYWORDS = (
    "ai engineer",
    "applied ai engineer",
    "agentic ai",
    "ai agent architect",
    "ai evals engineer",
    "ai quality engineer",
    "ai scraping engineer",
    "ai scraping specialist",
    "context engineer",
    "ai big data engineer",
    "forward deployed ai engineer",
    "ai solutions engineer",
    "ai solutions architect",
    "ai software engineer",
    "ai software integration engineer",
    "generative ai engineer",
    "genai engineer",
    "llm engineer",
    "llm application engineer",
    "prompt engineer",
    "machine learning engineer",
    "ml engineer",
    "deep learning engineer",
    "nlp engineer",
    "computer vision engineer",
    "ml research engineer",
    "ai research scientist",
    "nlp research scientist",
    "mlops engineer",
    "llmops engineer",
    "ai platform engineer",
    "ai reliability engineer",
    "ai sre",
    "ai architect",
    "multi-agent orchestration engineer",
    "ai-to-ai protocol engineer",
    "agentic fintech engineer",
    "agentic finops engineer",
    "agent guardrail engineer",
    "agent boundary engineer",
    "deterministic fallback engineer",
    "ai lineage engineer",
    "ai provenance engineer",
    "slm optimization engineer",
    "spatial ai context engineer",
    "agentic sre",
)

# Engineering families next to SWE that the candidate applies to as well
# (owner, 2026-10-07): ML Ops / ML infrastructure, security and data engineering.
ADJACENT_ENGINEERING_TITLE_PATTERNS = (
    r"\bml\s?ops\b",
    r"\bsecurity engineer\b",
    r"\bdata engineer\b",
)


def normalize_title(title: str) -> str:
    cleaned = re.sub(r"[^\w\s]", "", title.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_company(company: str) -> str:
    cleaned = re.sub(r"(inc|llc|corp|corporation|ltd|co)\b", "", company.lower(), flags=re.I)
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_location(location: str) -> str:
    cleaned = re.sub(r"[^\w\s]", "", (location or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


# Hosts that serve a job description rather than an application form. A posting
# stored under one of these is unapplyable until it has been resolved to the
# employer's own board.
UNAPPLYABLE_LISTING_HOSTS: frozenset[str] = frozenset({
    "www.indeed.com", "indeed.com", "in.indeed.com", "uk.indeed.com",
    "www.linkedin.com", "linkedin.com",
    "www.glassdoor.com", "glassdoor.com",
    "www.ziprecruiter.com", "ziprecruiter.com",
    "jaabz.com", "www.jaabz.com",
    "himalayas.app", "www.himalayas.app",
    "jobicy.com", "www.jobicy.com",
    "remoteok.com", "remoteok.io",
    "weworkremotely.com", "www.weworkremotely.com",
    "news.ycombinator.com",
})


def _is_unapplyable_listing_url(app_url: str) -> bool:
    from urllib.parse import urlparse

    try:
        host = (urlparse(app_url).netloc or "").lower()
    except ValueError:
        return False
    return host in UNAPPLYABLE_LISTING_HOSTS


def canonical_ats_posting_id(app_url: str) -> str:
    """The ATS's own posting id, when the URL carries one.

    The same posting is published under several host/path shapes — Greenhouse
    alone serves `boards.greenhouse.io/<co>/jobs/123`,
    `job-boards.greenhouse.io/<co>/jobs/123`, the regional
    `boards.eu.greenhouse.io/...`, and the employer's own branded mirror with
    `?gh_jid=123`. Keying dedup on netloc+path treats every one of those as a
    different job (54 such groups observed live in a 5,003-job queue), so the
    stable ATS id is preferred whenever it can be read off the URL.
    """
    from urllib.parse import parse_qs, urlparse

    if not app_url:
        return ""
    parsed = urlparse(app_url)
    host = (parsed.netloc or "").lower()
    qs = parse_qs(parsed.query)

    # The employer's branded mirror and the aggregator copies both carry the
    # Greenhouse id explicitly, which is the whole point of the parameter.
    gh_jid = (qs.get("gh_jid") or [""])[0].strip()
    if gh_jid.isdigit():
        return f"gh:{gh_jid}"

    if "greenhouse.io" in host:
        m = re.search(r"/jobs/(\d{4,})", parsed.path)
        if m:
            return f"gh:{m.group(1)}"

    if "lever.co" in host:
        m = re.search(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", parsed.path, re.I)
        if m:
            return f"lever:{m.group(1).lower()}"

    if "ashbyhq.com" in host:
        m = re.search(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", parsed.path, re.I)
        if m:
            return f"ashby:{m.group(1).lower()}"

    # Jobvite keys the posting on `?j=`, and repeats the same posting once per
    # location with a differing `loc=`. Observed live: one AppFolio opening came
    # back from Indeed as nine rows sharing `j=of3MAfwo`.
    if "jobvite.com" in host:
        jv = (qs.get("j") or [""])[0].strip()
        if jv:
            return f"jobvite:{jv.lower()}"

    # SmartRecruiters puts the posting id in the last path segment.
    if "smartrecruiters.com" in host:
        m = re.search(r"/(\d{6,})(?:/|$)", parsed.path)
        if m:
            return f"smartrecruiters:{m.group(1)}"

    return ""


def normalize_application_url(app_url: str) -> str:
    """Host and path, lowercased, with the query and any trailing slash dropped.

    This exists because the composite key is not enough on its own to tell
    Browse that Autopilot already has a posting. The key prefers the ATS's own
    id when the URL carries one, so the same Datadog posting reached as
    `careers.datadoghq.com/detail/3851935` (no id in the URL) and as
    `careers.datadoghq.com/detail/3851935/?gh_jid=3851935` (id present) hashes
    two different ways: one keys on the clean URL, the other on `gh:3851935`.
    Measured live, that mismatch alone left 580 postings on the Browse page
    that Autopilot was already holding.

    Normalising to host+path catches exactly that case, because the two URLs
    differ only in the query string and a trailing slash. It stays deliberately
    strict about the path: two different posting ids under the same employer
    are two different openings, and folding them together on company and title
    alone would hide real jobs.
    """
    if not app_url:
        return ""
    from urllib.parse import urlparse

    parsed = urlparse(app_url.strip())
    host = (parsed.netloc or "").lower().removeprefix("www.")
    path = (parsed.path or "").rstrip("/")
    if not host and not path:
        return ""
    return f"{host}{path}".lower()


def generate_composite_job_key(
    company: str, title: str, app_url: str = "", external_id: str = "", location: str = "",
) -> str:
    norm_c = normalize_company(company)
    norm_t = normalize_title(title)
    # The ATS's own posting id comes first, ahead of `external_id`. Both identify
    # the posting for an ATS-native source (Greenhouse's `externalJobId` *is* the
    # id in its URL), but only this one is stable across sources: an aggregator
    # supplies its own per-listing id, which is unique per row and therefore
    # makes the key unique by construction. Measured live — 578 Indeed rows
    # produced 578 distinct keys, so neither the existing queue nor two copies of
    # the same posting could ever match, and one AppFolio opening came through
    # nine times.
    canonical_id = canonical_ats_posting_id(app_url)
    if canonical_id:
        return f"{norm_c}::{norm_t}::{canonical_id}"
    if external_id:
        return f"{norm_c}::{norm_t}::{external_id.lower().strip()}"
    if app_url:
        from urllib.parse import urlparse
        parsed = urlparse(app_url)
        clean_url = f"{parsed.netloc}{parsed.path}".rstrip("/")
        return f"{norm_c}::{norm_t}::{clean_url}"
    # Neither a job id nor a URL to key on — the weakest signal available, so
    # location is folded in here (and only here) as an extra dimension. It is
    # deliberately left out of the id/url branches above: those already
    # identify one specific posting, and a posting stored with location
    # missing on one copy but not the other must not be treated as a
    # different job just because that field is inconsistently populated.
    return f"{norm_c}::{norm_t}::{normalize_location(location)}"


def build_existing_key_index(existing_jobs: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Composite key -> set of statuses, computed once instead of per candidate.

    ``evaluate_hard_filters`` used to recompute every existing job's composite
    key from scratch (two regex substitutions plus a urlparse) on every single
    call, inside a loop over every candidate job — O(candidates x existing).
    With a few hundred candidates against ~2,000 existing jobs that is enough
    string processing to peg a CPU core for tens of seconds per refill cycle
    and stall the whole (single-worker) API process for every other request.
    Building this index once per batch turns the check into an O(1) lookup.
    """
    index: dict[str, set[str]] = {}
    for existing in existing_jobs:
        key = generate_composite_job_key(
            existing.get("company") or "",
            existing.get("title") or "",
            existing.get("applicationUrl") or "",
            existing.get("externalJobId") or "",
            existing.get("location") or "",
        )
        index.setdefault(key, set()).add(existing.get("status") or "")
    return index


# Applied to any posting known to be outside the United States. Large enough to
# sink it below every US posting regardless of match score or recency, while
# leaving international postings ordered sensibly among themselves — "US first,
# other countries at the end", not "other countries never".
INTERNATIONAL_QUEUE_PENALTY = 10_000_000.0

# Queue ordering is lexicographic, packed into one number so every caller can
# keep sorting on a single float: recency band, then role rank, then location
# tier, then freshness within the band, then match score. Each weight is larger
# than the most everything below it can add up to.
RECENCY_BAND_WEIGHT = 1_000_000.0
ROLE_RANK_WEIGHT = 100_000.0
LOCATION_TIER_WEIGHT = 10_000.0
FRESHNESS_WEIGHT = 1_000.0


def is_international_location(job: dict[str, Any]) -> bool:
    """Whether a posting is known to sit outside the United States.

    Deliberately conservative and shaped like the hard filter's own test: a
    location that names a non-US country counts as international *unless* it
    also carries strong US evidence, so "Remote, Canada; Remote, United States"
    and "Vienna, Virginia" stay US. Anything unknown is treated as US so a
    missing location never silently sinks a domestic posting.
    """
    loc = (job.get("location") or "").lower()
    if not loc:
        return False
    if not any(c in loc for c in _NON_US_COUNTRY_MARKERS):
        return False
    return not any(ind in loc for ind in _STRONG_US_MARKERS)


# Kept narrow on purpose: only tokens that unambiguously name a foreign country
# or city. The hard filter owns the exhaustive list; this is the ranking-time
# test and a miss here costs ordering, not correctness.
_NON_US_COUNTRY_MARKERS = (
    "argentina", "australia", "austria", "bangladesh", "belgium", "bolivia",
    "brazil", "bulgaria", "canada", "chile", "china", "colombia", "costa rica",
    "croatia", "czech", "denmark", "ecuador", "egypt", "estonia", "finland",
    "france", "germany", "ghana", "greece", "guatemala", "honduras",
    "hong kong", "hungary", "india", "indonesia", "ireland", "israel", "italy",
    "japan", "jordan", "kenya", "latvia", "lithuania", "malaysia", "mexico",
    "morocco", "netherlands", "new zealand", "nicaragua", "nigeria", "norway",
    "pakistan", "panama", "paraguay", "peru", "philippines", "poland",
    "portugal", "qatar", "romania", "russia", "russian federation", "saudi", "serbia", "singapore", "slovakia",
    "slovenia", "south africa", "south korea", "spain", "sri lanka", "sweden",
    "switzerland", "taiwan", "thailand", "tunisia", "turkey", "uae", "ukraine",
    "united kingdom", "uruguay", "venezuela", "vietnam",
    # Cities distinctive enough to name a country on their own.
    "amsterdam", "ankara", "athens", "bangalore", "barcelona", "belgrade",
    "berlin", "bogota", "brussels", "bucharest", "budapest", "buenos aires",
    "copenhagen", "dubai", "dublin", "gdansk", "helsinki", "hyderabad",
    "istanbul", "kiev", "kyiv", "lima", "lisbon", "london", "madrid", "manila",
    "milan", "moscow", "munich", "oslo", "paris", "prague", "riga", "rio de janeiro",
    "rome", "santiago", "sao paulo", "seoul", "sofia", "stockholm", "sydney",
    "tallinn", "tel aviv", "tokyo", "toronto", "vancouver", "vienna", "vilnius",
    "warsaw", "zurich", "krakow",
    # Indian metros beyond Bangalore/Hyderabad — an Agoda "Gurugram" posting
    # ranked third on the US-first list before these were added.
    "gurugram", "gurgaon", "noida", "pune", "chennai", "mumbai", "new delhi",
    "kolkata", "ahmedabad", "kochi", "coimbatore", "trivandrum", "mysore",
    "bengaluru", "jaipur", "chandigarh", "indore",
    # Other frequently-seen metros.
    "montreal", "ottawa", "calgary", "edinburgh", "manchester", "birmingham uk",
    "guadalajara", "monterrey", "medellin", "montevideo", "quito", "san jose costa rica",
    "cairo", "nairobi", "lagos", "karachi", "lahore", "dhaka", "colombo",
    "ho chi minh", "hanoi", "jakarta", "kuala lumpur", "bangkok", "shenzhen",
    "shanghai", "beijing", "osaka", "melbourne", "brisbane", "perth", "auckland",
    "wellington", "cape town", "johannesburg",
    "emea", "apac", "latam",
)

# Strong enough to mean "this posting is open to US candidates" even when the
# location also names somewhere else.
_STRONG_US_MARKERS = (
    "united states", "usa", "u.s.", ", us", "remote - us", "remote (us",
    "us remote", "remote in us", "nyc", "new york",
)


_MANAGEMENT_MARKERS = (
    "director", "manager", "head of", "vp", "vice president", "chief", "managing director",
)
_NON_ENGINEERING_MARKERS = (
    "sales engineer", "solution architect", "account executive", "designer", "recruiter",
    "talent", "marketing", "human resources", "counsel", "legal", "business analyst",
)
_ENGINEER_TITLE = re.compile(r"\b(?:engineer|developer|sde|swe)\b")
_EXPLICIT_IC = re.compile(r"\bic\b|individual contributor")
_PEOPLE_LEADER = re.compile(r"people (?:leader|manager)")


def _has_marker(title_l: str, markers: Iterable[str]) -> list[str]:
    return [m for m in markers if re.search(rf"\b{re.escape(m)}\b", title_l)]


def is_management_title(title: str) -> bool:
    """Whether a title is a people-management role rather than an IC one.

    An engineer title that says outright it is an individual-contributor role
    ("Full-stack Engineer 4 (Manager, IC)") is not management despite the word.
    Bank corporate ranks ("Vice President, Senior Full Stack Engineer") stay
    excluded by the candidate's choice.
    """
    title_l = (title or "").lower()
    if _PEOPLE_LEADER.search(title_l):
        return True
    if not _has_marker(title_l, _MANAGEMENT_MARKERS):
        return False
    return not (_ENGINEER_TITLE.search(title_l) and _EXPLICIT_IC.search(title_l))

# Greater Seattle / Washington State. "Washington, D.C." is the opposite side of
# the country and must never match. The bare "wa" token is matched on letter
# boundaries so "Iowa," "Ottawa" and "Hawaii" do not read as Washington.
_DC_LOCATION = re.compile(r"district of columbia|washington,?\s*d\.?c\b")
_WA_LOCATION = re.compile(
    r"\b(?:seattle|bellevue|redmond|kirkland|bothell|renton|issaquah|sammamish|"
    r"woodinville|tacoma|spokane|washington)\b|(?<![a-z])wa(?![a-z])"
)

_FORWARD_DEPLOYED = re.compile(r"\bforward[\s\-]?deployed\s+(?:\w+\s+)?engineer\b")
_SDE_2 = re.compile(r"\b(?:sde|swe|engineer|developer)\s*(?:ii|2)\b|\bmid[\s\-]level\b")
_SDE_1 = re.compile(
    r"\b(?:sde|swe|engineer|developer)\s*(?:i|1)\b|\bjunior\b|\bentry[\s\-]level\b|\bnew\s+grad"
)

# Candidate's role order, best first: Senior, Forward Deployed Engineer,
# Principal, SDE 2, Staff, SDE 1. Anything else that qualifies ranks 0.
ROLE_RANK_SENIOR = 6
ROLE_RANK_FORWARD_DEPLOYED = 5
ROLE_RANK_PRINCIPAL = 4
ROLE_RANK_SDE_2 = 3
ROLE_RANK_STAFF = 2
ROLE_RANK_SDE_1 = 1


def is_washington_location(job: dict[str, Any]) -> bool:
    """Seattle, Bellevue, Redmond or anywhere else in Washington State."""
    loc_l = (job.get("location") or "").lower()
    if not loc_l and isinstance(job.get("metadata"), dict):
        loc_l = (job["metadata"].get("location") or "").lower()
    return bool(loc_l) and not _DC_LOCATION.search(loc_l) and bool(_WA_LOCATION.search(loc_l))


def role_priority_rank(title: str) -> int:
    """Rank of a title in the candidate's role order; higher applies first."""
    title_l = _MEMBER_OF_TECHNICAL_STAFF.sub("software engineer", (title or "").lower())
    is_senior, _ = role_level_flags(title_l)
    if is_senior:
        return ROLE_RANK_SENIOR
    if _FORWARD_DEPLOYED.search(title_l):
        return ROLE_RANK_FORWARD_DEPLOYED
    if re.search(r"\bprincipal\b", title_l):
        return ROLE_RANK_PRINCIPAL
    if _SDE_2.search(title_l):
        return ROLE_RANK_SDE_2
    if re.search(r"\bstaff\b", title_l):
        return ROLE_RANK_STAFF
    if _SDE_1.search(title_l):
        return ROLE_RANK_SDE_1
    return 0


def role_location_priority_bonus(job: dict[str, Any]) -> float:
    """Candidate-preference bonus: role rank first, then location tier.

    Roles follow ``role_priority_rank`` (Senior anywhere in the US beats any
    Forward Deployed role, and so on). Within a role, Washington State (Seattle,
    Bellevue, Redmond and the rest of WA) beats the rest of the US.
    Management and non-engineering titles get nothing.
    """
    title_l = (job.get("title") or "").lower()
    if is_management_title(title_l) or _has_marker(title_l, _NON_ENGINEERING_MARKERS):
        return 0.0
    if any(re.search(rf"\b{k}\b", title_l) for k in ("intern", "internship", "co-op", "apprentice")):
        return 0.0
    is_engineering = any(k in title_l for k in (
        "software", "backend", "back end", "full stack", "fullstack", "frontend",
        "front end", "platform", "infrastructure", "systems", "distributed",
        "engineer", "developer", "sde", "swe", *AI_ML_TITLE_KEYWORDS,
    ))
    if not is_engineering:
        return 0.0
    location_tier = 1 if is_washington_location(job) else 0
    return location_tier * LOCATION_TIER_WEIGHT + role_priority_rank(title_l) * ROLE_RANK_WEIGHT


_MEMBER_OF_TECHNICAL_STAFF = re.compile(r"\bmember\s+of\s+(?:the\s+)?technical\s+staff\b")


def role_level_flags(title_l: str) -> tuple[bool, bool]:
    """(is_senior, is_staff_or_principal) for an individual-contributor engineering title."""
    # "Member of Technical Staff" is a software engineer title; its "staff" is not a level.
    title_l = _MEMBER_OF_TECHNICAL_STAFF.sub("software engineer", title_l)
    above_senior_markers = (
        "staff", "principal", "distinguished", "fellow", "architect", "lead",
    )
    is_above_senior = any(re.search(rf"\b{re.escape(k)}\b", title_l) for k in above_senior_markers)
    engineering = any(k in title_l for k in (
        "software", "backend", "full stack", "frontend", "platform",
        "infrastructure", "systems", "cloud", "security", "data",
        "engineer", "developer", "sde", "swe", *AI_ML_TITLE_KEYWORDS,
    ))

    is_senior = (
        any(k in title_l for k in (
            "senior", "sr.", "sr ", "sr-", "senior swe",
            "sde iii", "sde 3", "swe iii", "swe 3",
            "software engineer iii", "software engineer 3",
        ))
        and engineering
        and not is_above_senior
    )
    is_staff_or_principal = (
        is_above_senior
        and any(re.search(rf"\b{re.escape(k)}\b", title_l) for k in ("staff", "principal", "lead", "distinguished", "fellow"))
        and engineering
    )
    return is_senior, is_staff_or_principal


def software_role_rejection(title: str) -> str | None:
    """Why ``title`` is not a qualifying individual-contributor software role, else None."""
    title_lower = title.lower()
    swe_keywords = [
        "software engineer",
        "software developer",
        "full stack",
        "fullstack",
        "backend",
        "back end",
        "frontend",
        "front end",
        "platform engineer",
        "systems engineer",
        "infrastructure engineer",
        "distributed systems",
        "devops",
        "site reliability",
        "sre",
        "applications engineer",
        "application engineer",
        "swe",
        # Missing until 2026-09-15, and rejecting real postings in bulk: Esri,
        # Zscaler and others title the role "Software Development Engineer"
        # at every level, and "Full-Stack" is usually hyphenated.
        "software development engineer",
        "software engineer in test",
        "full-stack",
        *AI_ML_TITLE_KEYWORDS,
    ]
    # Short role codes and "product engineer" need word boundaries: "sde" must
    # not match inside another word, and "product engineer" must not pull in
    # "product security engineer" or any sales/presales title.
    swe_patterns = (
        r"\bsde\b",
        r"\bsdet\b",
        r"\bproduct engineer\b",
        _FORWARD_DEPLOYED.pattern,
        _MEMBER_OF_TECHNICAL_STAFF.pattern,
        *ADJACENT_ENGINEERING_TITLE_PATTERNS,
    )
    # Recruiting roles name the team they hire for ("Technical Sourcer, Research
    # SWE"), so the engineering keywords alone would let them through.
    if re.search(r"\b(sourcer|recruiter|recruiting\s+(coordinator|partner|lead))\b", title_lower):
        return f"Role '{title}' is a recruiting role, not a Software Engineering role"
    # "Senior Electrical Infrastructure Engineer" matches "infrastructure engineer".
    if "software" not in title_lower and re.search(
        r"\b(electrical|mechanical|civil|chemical|structural|hvac)\b", title_lower
    ):
        return f"Role '{title}' is a physical engineering discipline, not a Software Engineering role"
    is_swe_role = any(kw in title_lower for kw in swe_keywords) or any(
        re.search(pattern, title_lower) for pattern in swe_patterns
    )
    if not is_swe_role:
        return f"Role '{title}' is not a Software Engineering role"

    if is_management_title(title_lower):
        return f"Role '{title}' is a management/director position"

    # Exclude internship / co-op / apprentice / student postings for experienced candidate
    intern_keywords = ("intern", "internship", "co-op", "apprentice", "working student", "fellowship")
    if any(re.search(rf"\b{kw}\b", title_lower) for kw in intern_keywords):
        return f"Role '{title}' is an internship or apprentice position"

    # Only Senior, Staff/Principal, or qualifying SWE roles are applied to (#59).
    is_sen, is_sop = role_level_flags(title_lower)
    is_other_swe = any(k in title_lower for k in (
        "software", "backend", "back end", "full stack", "fullstack", "frontend",
        "front end", "platform", "infrastructure", "systems", "distributed",
        "engineer", "developer", "sde", "swe", *AI_ML_TITLE_KEYWORDS,
    ))
    if not (is_sen or is_sop or is_other_swe):
        return f"Role '{title}' is not a qualifying software engineering role"
    return None


def duplicate_block_reason(job: dict[str, Any], existing_key_index: dict[str, set[str]]) -> str | None:
    """Why ``job`` duplicates a posting already queued, in flight or applied to, else None."""
    job_key = generate_composite_job_key(
        job.get("company") or "",
        job.get("title") or "",
        job.get("applicationUrl") or job.get("listingUrl") or "",
        job.get("externalJobId") or "",
        job.get("location") or "",
    )
    for ex_status in existing_key_index.get(job_key) or set():
        if ex_status in (
            AutopilotJobStatus.SUBMITTED.value,
            AutopilotJobStatus.APPLYING.value,
            AutopilotJobStatus.STAGED.value,
            "NEEDS_REVIEW",
            AutopilotJobStatus.QUEUED.value,
        ):
            return f"Duplicate application already in state: {ex_status}"
    return None


def evaluate_hard_filters(
    job: dict[str, Any],
    profile: dict[str, Any],
    existing_jobs: list[dict[str, Any]] | dict[str, set[str]],
    settings: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Perform deterministic pre-checks before executing AI match scoring.

    ``existing_jobs`` accepts either the raw job list (rebuilds the key index
    every call — fine for a one-off check) or a pre-built index from
    ``build_existing_key_index`` (O(1) lookup — required for any caller that
    invokes this per candidate in a loop; see that function's docstring).

    Returns (passed, skip_reason).
    """
    opts = settings or {}
    max_age_days = opts.get("maxPostAgeDays", DEFAULT_MAX_POST_AGE_DAYS)

    company = job.get("company") or ""
    title = job.get("title") or ""
    app_url = job.get("applicationUrl") or job.get("listingUrl") or ""

    if not company or not title:
        return False, "Missing company or job title"

    # A posting with no URL — or one pointing at a careers *index* rather than a
    # specific job — can never be applied to. Without this the executor opens
    # the listing page, fills nothing, and fails with "Submit button not found",
    # burning a full browser session per attempt.
    if not app_url:
        return False, "Posting has no application URL"

    # An aggregator's own listing page is not an application form. Indeed and
    # LinkedIn both serve a job *description* at these URLs with no form on it,
    # so the executor opens the page, finds nothing to fill and parks the job in
    # MANUAL_REVIEW — one wasted browser session each, and the posting can never
    # succeed no matter how often it is retried.
    #
    # This is enforced here rather than in each source so no future aggregator
    # can reintroduce it. Measured when it did: 326 autopilot jobs carried an
    # indeed.com/linkedin.com URL, 241 of them already parked in manual review.
    # Such a posting is only usable once it has been resolved to the employer's
    # own board (see resolve_by_company_and_title / the redirect resolver).
    if _is_unapplyable_listing_url(app_url):
        return False, (
            f"Application URL '{app_url}' is an aggregator listing page, not an "
            "employer application form"
        )

    url_path, _, url_query = app_url.partition("?")
    if re.search(r"/(?:jobs|careers|openings|positions)/?$", url_path, flags=re.I):
        # Many boards keep the index path and identify the posting in the query
        # instead (`/en/jobs/?gh_jid=7849003`), so only a URL that names no job
        # anywhere is an index.
        if not re.search(r"=\d{3,}", url_query):
            return False, f"Application URL '{app_url}' is a careers index, not a specific posting"

    # 1. Duplicate Application Protection
    if not opts.get("allowDuplicates", False):
        existing_key_index = existing_jobs if isinstance(existing_jobs, dict) else build_existing_key_index(existing_jobs)
        duplicate = duplicate_block_reason(job, existing_key_index)
        if duplicate:
            return False, duplicate

    # 1b. Company Application Cap (Max 50 applications per company)
    company_norm = re.sub(r"[^\w]", "", company.lower())
    comp_cap = int(opts.get("maxCompanyApplications") or 50)
    company_counts = opts.get("companySubmittedCounts")
    if company_counts and isinstance(company_counts, dict):
        if company_counts.get(company_norm, 0) >= comp_cap:
            return False, f"Company '{company}' has reached the {comp_cap} application cap"

    # 2. Posting Recency Check
    date_posted_str = job.get("datePosted") or job.get("dateDiscovered") or job.get("updatedAt") or job.get("createdAt") or ""
    if date_posted_str:
        try:
            posted_date = datetime.fromisoformat(str(date_posted_str).replace("Z", "+00:00"))
            if posted_date.tzinfo is None:
                posted_date = posted_date.replace(tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
            if posted_date < cutoff:
                return False, f"Posting age exceeds limit ({max_age_days} days)"
        except Exception:
            pass

    # 3. Role Title Filter (Software Engineering Roles Only)
    title_lower = title.lower()
    role_rejection = software_role_rejection(title)
    if role_rejection:
        return False, role_rejection

    # 4. Location Filter (United States Positions Only)
    job_loc = (job.get("location") or "").lower()
    job_wp = (job.get("workplaceType") or "").lower()
    
    # Check for international non-US countries / locations to exclude
    non_us_indicators = [
        "poland", "warsaw", "krakow", "uk", "united kingdom", "london",
        "canada", "toronto", "vancouver", "germany", "berlin", "munich",
        "india", "bangalore", "hyderabad", "france", "paris", "brazil",
        "australia", "sydney", "singapore", "ireland", "dublin", "japan",
        "tokyo", "china", "emea", "apac", "latam", "mexico", "netherlands",
        "amsterdam", "spain", "madrid", "barcelona", "sweden", "stockholm",
        "chile", "argentina", "colombia", "turkey", "peru", "ecuador",
        "uruguay", "venezuela", "bolivia", "paraguay", "costa rica",
        "panama", "guatemala", "el salvador", "honduras", "nicaragua",
        "dominican republic", "bogota", "buenos aires", "santiago",
        "lima", "istanbul", "ankara", "sao paulo", "rio de janeiro",
        "portugal", "lisbon", "italy", "rome", "milan", "switzerland",
        "zurich", "austria", "vienna", "belgium", "brussels", "denmark",
        "copenhagen", "norway", "oslo", "finland", "helsinki", "israel",
        "tel aviv", "south africa", "philippines", "manila", "vietnam",
        "indonesia", "malaysia", "thailand", "south korea", "seoul",
        "new zealand", "egypt", "nigeria", "kenya", "uae", "dubai",
        "hungary", "budapest", "czech", "prague", "romania", "bucharest",
        "bulgaria", "sofia", "greece", "athens", "ukraine", "kyiv", "kiev",
        "serbia", "belgrade", "croatia", "slovakia", "slovenia", "lithuania",
        "latvia", "estonia", "tallinn", "riga", "vilnius", "pakistan",
        "bangladesh", "sri lanka", "morocco", "tunisia", "ghana", "taiwan",
        "hong kong", "saudi", "qatar", "jordan", "armenia", "georgia (country)",
    ]
    # Strong US evidence: phrases, full state names and major US cities, safe to
    # match as substrings. A location naming one of these is a US-eligible
    # posting even when it also lists other countries ("Remote, Canada; Remote,
    # United States", "Vienna, Virginia, United States", "SF, NY, Portland, or
    # Remote within US/Canada") - those were all rejected as non-US before.
    us_indicators = [
        "united states", "usa", "u.s.", "remote - us", "remote (us", "us remote",
        "remote in us", ", us", ", usa", "nyc", "new york city",
        "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
        "connecticut", "delaware", "florida", "hawaii", "idaho", "illinois",
        "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine", "maryland",
        "massachusetts", "michigan", "minnesota", "mississippi", "missouri",
        "montana", "nebraska", "nevada", "new hampshire", "new jersey",
        "new mexico", "new york", "north carolina", "north dakota", "ohio",
        "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
        "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
        "washington", "wisconsin", "wyoming",
        "seattle", "bellevue", "redmond", "austin", "san francisco", "boston",
        "los angeles", "chicago", "atlanta", "denver", "miami", "dallas",
        "houston", "phoenix", "philadelphia", "san diego", "san jose",
        "palo alto", "mountain view", "menlo park", "portland", "pittsburgh",
        "raleigh", "salt lake city", "minneapolis", "detroit", "nashville",
        "indianapolis", "santa clara", "cupertino", "sunnyvale",
        "redwood city", "foster city", "milpitas", "santa rosa",
        "hayward", "fremont", "oakland", "berkeley", "richmond",
        "santa monica", "burbank", "glendale", "long beach",
        "anaheim", "irvine", "santa barbara", "camarillo",
        "oxnard", "thousand oaks", "palmdale", "lancaster",
    ]
    # Weak US evidence: state abbreviations and short city codes, matched as
    # whole tokens only ("Budapest, Hungary" contains "ga", "Poland" contains
    # "la"). Weak evidence alone never outweighs a named non-US place:
    # "Hyderabad, in" is India, not Indiana, and "CA-Ontario-Toronto" is Canada.
    us_state_abbr = {
        "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
        "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
        "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
        "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
        "wi", "wy", "dc", "us", "usa", "sf", "nyc",
    }
    # Locations that name no country at all. Treated like a bare "remote": the
    # posting is not known to be outside the US, so it is not rejected for it.
    ambiguous_location = re.compile(
        r"^\s*$|hybrid|in[- ]office|on[- ]?site|multiple locations|\b\d+\s+locations?\b|flexible"
        r"|\banywhere\b|\bworldwide\b",
        flags=re.I,
    )

    # Opt-in (profile.allowInternationalLocations): postings outside the United
    # States are no longer rejected at all. They still rank below every US
    # posting, because queue_priority_score applies INTERNATIONAL_QUEUE_PENALTY.
    allow_international = str(profile.get("allowInternationalLocations", "")).strip().lower() in (
        "yes", "true", "1",
    )

    if job_loc or title_lower:
        strong_us = any(ind in job_loc for ind in us_indicators)
        tokens = {t.strip(" .;|()") for t in re.split(r"[,\s/\-]+", job_loc)} if job_loc else set()
        weak_us = bool(tokens & us_state_abbr)
        # "uk" is the one indicator short enough to hide inside ordinary words
        # ("Milwaukee", "Duke Energy"), so it only counts as a whole token.
        title_tokens = {t.strip(" .;|()") for t in re.split(r"[,\s/\-]+", title_lower)}
        names_non_us = any(
            country in job_loc or country in title_lower
            for country in non_us_indicators if country != "uk"
        ) or "uk" in tokens or "uk" in title_tokens

        if names_non_us and not strong_us and not allow_international:
            return False, f"Location '{job.get('location')}' is outside the United States"

        # A region in the title is the employer saying who the role is for, and
        # it outranks US-looking location text: "LATAM Software Engineer" listed
        # "Virgin Islands, U.S." and "Core Product (Europe)" listed "Remote
        # (United States)", and both were applied to.
        title_region = re.search(
            r"\b(latam|latin america|europe|emea|apac|canada|uk|united kingdom|india|"
            r"mexico|brazil|germany|poland|ireland|australia|singapore|japan)\b",
            title_lower,
        )
        title_names_us = bool(title_tokens & {"us", "usa"}) or any(ind in title_lower for ind in us_indicators)
        if title_region and not title_names_us and not allow_international:
            return False, f"Title '{job.get('title')}' is for {title_region.group(1).upper()}, not the United States"

        if job_loc and not names_non_us and not allow_international:
            has_us_marker = strong_us or weak_us or "remote" in job_loc or bool(ambiguous_location.search(job_loc))
            if not has_us_marker:
                return False, f"Location '{job.get('location')}' does not match United States criteria"

    # 5. Employment Type Constraints
    job_emp = (job.get("employmentType") or "").lower()
    pref_emp = (profile.get("preferredEmploymentType") or "").lower()
    if pref_emp and job_emp and pref_emp not in job_emp and "full" in pref_emp and "part" in job_emp:
        return False, f"Employment type mismatch: job is {job_emp}, preferred is {pref_emp}"

    profile_loc = (profile.get("location") or "").lower()
    remote_pref = profile.get("remoteOnly", False)

    if remote_pref and "remote" not in job_wp and "remote" not in job_loc:
        return False, "Job is not Remote, candidate requires Remote Only"

    # 6. US Citizenship & Visa Sponsorship / ITAR Defense Filter
    needs_sponsorship = (
        str(profile.get("sponsorship", "")).strip().lower() in ("yes", "true", "1")
        or str(profile.get("requiresSponsorship", "")).strip().lower() in ("yes", "true", "1")
    )
    is_us_citizen = str(profile.get("usCitizen", "")).strip().lower() in ("yes", "true", "1")

    norm_c = normalize_company(company)
    # Defense / aerospace contractors known to strictly require US citizenship under ITAR / EAR
    known_itar_defense_companies = {
        "anduril",
        "anduril industries",
        "spacex",
        "lockheed",
        "lockheed martin",
        "northrop",
        "northrop grumman",
        "raytheon",
        "rtx",
        "general dynamics",
        "boeing defense",
        "l3harris",
        "bae systems",
        "sierra nevada",
        "palantir defense",
    }
    if any(c in norm_c for c in known_itar_defense_companies):
        return False, f"Company '{company}' is a Defense/ITAR contractor (excluded per user preference)"

    # Companies excluded per user preference (e.g. an existing offer elsewhere) -
    # not a fit/eligibility signal, just a do-not-apply list.
    excluded_companies = {
        "alaska airlines",
    }
    if any(c in norm_c for c in excluded_companies):
        return False, f"Company '{company}' is excluded per user preference"

    # Exclude boards with hard bot protection that block automated headless runs
    #
    # Live-tested 2026-09-14 rather than trusted as a static guess (see git
    # history for the brief window this was disabled). Two lines of evidence
    # that DISAGREE, both real:
    #  1. CareerOS's own stealth Playwright browser hit an identical,
    #     reproducible `Timeout 60000ms exceeded` on page.goto across 3 real
    #     attempts against 2 queued postings, hanging with no progress until
    #     manually recovered each time - eventually settling on "no
    #     application form on the posting page".
    #  2. A plain manual Chrome session (not Playwright, no stealth args) hit
    #     a genuinely current Roblox posting - found by browsing Roblox's own
    #     live listings, not from the queue - and its real Greenhouse-hosted
    #     apply form (Resume/CV, Cover Letter, Legal Name...) loaded
    #     instantly with zero CAPTCHA/Turnstile/any bot-challenge visible.
    # So "Roblox uses Cloudflare Turnstile" (the original reason this block
    # existed) is likely just wrong - nothing challenged a normal browser.
    # The two automation postings tested were both from days-old discovery
    # batches and may simply have been expired/closed (one confirmed
    # redirecting to the generic careers page on manual navigation), which
    # would also explain a slow/odd load rather than an active bot-wall. This
    # was not re-isolated against a known-fresh posting through CareerOS's
    # own automation before time ran out, so the real cause (stale queue
    # entries vs. a genuine stealth-browser-specific load issue on this
    # board) is still open - see NIGHT_BATCH_DECISIONS.md. Re-enabling the
    # block for now since every real automation attempt failed, but the
    # reason is deliberately about the *symptom*, not a false "bot
    # protection" claim - a future session re-testing against a fresh
    # posting id could resolve this properly.
    # One specific, deliberate exception: job 8127056 (Senior Software
    # Engineer - Desktop) is a known-fresh, known-open posting confirmed by
    # hand to have no bot-challenge - added 2026-09-14 to get one clean,
    # confound-free automation result through CareerOS's own pipeline
    # (the earlier 3 test attempts both used likely-expired postings, so the
    # timeout cause was never actually isolated). Remove this once that
    # result is in - it is not meant to stand as a permanent carve-out.
    _ROBLOX_TEST_EXCEPTION_URLS = ("careers.roblox.com/jobs/8127056",)
    if "roblox" in norm_c and not any(u in app_url for u in _ROBLOX_TEST_EXCEPTION_URLS):
        return False, "Roblox's Greenhouse-hosted apply form reliably times out in CareerOS's automation (verified live 2026-09-14); a manual browser hit no challenge on a current posting, so this is unconfirmed as an actual bot-wall - see NIGHT_BATCH_DECISIONS.md"
    if "okta" in norm_c:
        return False, "Okta uses reCAPTCHA verification"

    if needs_sponsorship and not is_us_citizen:

        # Check job description and title text for ITAR and citizenship restrictions
        full_text = f"{title} {job.get('description', '')} {job.get('requirements', '')}".lower()
        itar_patterns = [
            r"\b(?:itar|ear)\b",
            r"\bu\.?s\.?\s+citizenship\s+required\b",
            r"\bu\.?s\.?\s+citizens?\s+only\b",
            r"\bsecurity clearance\b",
            r"\bclearance eligibility\b",
            r"\bu\.?s\.?\s+person\s+(?:status\s+)?required\b",
            r"\bmust be a (?:u\.s\.\s+)?person\b",
            r"\bexport control(?:led)?\b",
            r"\bno (?:visa )?sponsorship\b",
            r"\bnot (?:able to )?sponsor\b",
            r"\bunable to sponsor\b",
            r"\bwithout (?:visa )?sponsorship\b",
        ]
        for pat in itar_patterns:
            if re.search(pat, full_text, flags=re.I):
                return False, f"Position requires U.S. Citizenship / clearance or does not sponsor visas ({pat})"

    return True, ""


# How much a brand-new posting outranks an otherwise identical old one, and how
# quickly that advantage decays. Freshness is worth less than the
# location/level tier (hundreds of points) but comparable to a few points of
# match score, so it breaks ties between similar jobs without ever promoting a
# poorly-matched posting over a well-matched one.
def extract_posting_datetime(job: dict[str, Any]) -> datetime | None:
    """Extract and parse posting datetime with multi-format support.

    Checks datePosted, postingDate, postedAt, dateDiscovered, discoveredAt,
    queuedAt, createdAt in order, parsing ISO format and human-readable dates
    like 'October 1, 2026'.
    """
    candidates = (
        job.get("datePosted"),
        job.get("postingDate"),
        job.get("postedAt"),
        job.get("dateDiscovered"),
        job.get("discoveredAt"),
        job.get("queuedAt"),
        job.get("createdAt"),
    )
    for stamp in candidates:
        if not stamp:
            continue
        try:
            parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            try:
                from dateutil import parser as dateparser
                parsed = dateparser.parse(str(stamp))
            except Exception:
                continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _real_posting_age_hours(job: dict[str, Any]) -> float | None:
    """Hours since the job was posted/discovered, or None if unparseable."""
    dt = extract_posting_datetime(job)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def _is_senior_software_engineer_title(job: dict[str, Any]) -> bool:
    return "senior software engineer" in (job.get("title") or "").lower()


FRESH_POSTING_WINDOW_HOURS = 24.0


# Upper age bound (hours) of each recency band, newest first. Older or undated
# postings sit in the bottom band.
_RECENCY_BAND_HOURS = (24.0, 72.0, 168.0, 336.0, 720.0)


def posting_recency_band(job: dict[str, Any]) -> tuple[int, float]:
    """(band, freshness): band 5 is the last 24 hours down to 0 for over 30
    days or undated; freshness runs 1.0 -> 0.0 across the band."""
    age_hours = _real_posting_age_hours(job)
    if age_hours is None:
        return 0, 0.0
    lower = 0.0
    for index, upper in enumerate(_RECENCY_BAND_HOURS):
        if age_hours <= upper:
            freshness = 1.0 - max(0.0, age_hours - lower) / (upper - lower)
            return len(_RECENCY_BAND_HOURS) - index, freshness
        lower = upper
    return 0, 0.0


def posting_recency_bonus(job: dict[str, Any]) -> float:
    """Recency band (primary queue key) plus freshness within the band.

    The band weight dominates everything else, so a posting from the last 24
    hours outranks any older posting. Freshness inside a band is worth less
    than a role rank or location tier, so within the last 24 hours a Seattle
    Senior role posted 20 hours ago still beats a Remote-US one posted 1 hour ago.
    """
    band, freshness = posting_recency_band(job)
    return band * RECENCY_BAND_WEIGHT + freshness * FRESHNESS_WEIGHT


def queue_priority_score(job: dict[str, Any]) -> float:
    """The single number the persistent queue is ordered by.

    Lexicographic, highest first:
    1. Recency band (last 24 hours, 1-3 days, 3-7 days, 7-14 days, 14-30 days, older).
    2. Role: Senior, Forward Deployed, Principal, SDE 2, Staff, SDE 1, other.
    3. Location: Washington State (Seattle, Bellevue, Redmond, ...) over the rest of the US.
    4. Freshness within the band, then match score.
    International postings are penalized below every domestic posting.
    """
    international_penalty = (
        INTERNATIONAL_QUEUE_PENALTY if is_international_location(job) else 0.0
    )
    return (
        posting_recency_bonus(job)
        + role_location_priority_bonus(job)
        + float(job.get("matchScore") or 0.0)
        - international_penalty
    )


def filter_and_rank_jobs(
    db: Session | list[dict[str, Any]],
    raw_jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    settings: dict[str, Any] | None = None,
    *,
    precomputed_matches: dict[str, dict[str, Any]] | None = None,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Process a list of discovered jobs:

    1. Drop duplicates only (every other hard filter runs at apply time, #59)
    2. Attach the Mistral/Ollama resume-vs-JD match (precomputed by the queue
       preprocessor, or scored inline here when the caller has none)
    3. Filter by min match score threshold (with fallback so batch queue never starves)
    4. Sort by location/level tier, then match score, then date posted

    ``maxApplicationsPerRun``/``targetProcessCount`` of 0 (or absent) means *no
    limit* — the persistent queue is deliberately unbounded, and only the E2E
    submission count is capped.
    """
    opts = settings or {}
    min_score = float(opts.get("minMatchScore") or 0.0)
    max_apps = int(opts.get("maxApplicationsPerRun") or opts.get("targetProcessCount") or 0)

    existing_jobs = db if isinstance(db, list) else list_autopilot_jobs(db)
    matches = precomputed_matches or {}
    all_passing: list[dict[str, Any]] = []

    # Built once instead of re-derived from existing_jobs on every candidate
    # (see build_existing_key_index's docstring - that reduced an O(candidates
    # x existing) hot loop to O(candidates + existing)). Updated below as each
    # candidate passes, so two copies of the same posting discovered in this
    # same raw_jobs batch (e.g. scraped twice across different search result
    # pages) are caught against each other too, not only against jobs that
    # already existed before this batch ran - a real gap that let the same
    # posting get queued and submitted twice.
    existing_key_index = build_existing_key_index(existing_jobs)

    # Load resume text / accomplishments for the heuristic-fallback path
    # below (only reached when a posting has no Mistral score) when the
    # caller didn't already supply them and a real DB session is on hand to
    # load them from. Without this, the deterministic fallback - the only
    # scoring path that runs while the local LLM is off - matched purely
    # against structured profile fields, blind to anything only mentioned in
    # the resume's own prose or in recorded accomplishments.
    if documents is None and accomplishments is None and not isinstance(db, list):
        try:
            from app.db.store import get_kv, list_entities
            documents = get_kv(db, "documents") or {}
            accomplishments = list_entities(db, "accomplishment")
        except Exception:
            documents, accomplishments = {}, []

    for job in raw_jobs:
        # Only a duplicate is kept out of the queue (#59). Every other hard
        # filter - role, level, location, age, aggregator URL, CAPTCHA board -
        # is applied by the runner when it reaches the job, which SKIPs it (or
        # files it as INELIGIBLE / MANUAL_REVIEW) with the reason visible.
        if not opts.get("allowDuplicates", False) and duplicate_block_reason(job, existing_key_index):
            continue

        match = matches.get(str(job.get("id") or "")) or job.get("mistralMatch")
        if isinstance(match, dict) and match.get("matchScore") is not None:
            score = float(match.get("matchScore") or 0.0)
            ranked_job = {
                **job,
                "matchScore": score,
                "matchReason": match.get("matchReason", ""),
                "keyMatchingSkills": match.get("keyMatchingSkills") or [],
                "missingSkills": match.get("missingSkills") or [],
                "matchMethod": match.get("matchMethod", "ollama-local"),
                "matchModel": match.get("matchModel", ""),
                # Kept so existing UI/reporting that reads matchReasons still
                # renders something meaningful now that the real explanation is
                # a sentence rather than a bag of keywords.
                "matchReasons": (match.get("keyMatchingSkills") or [])[:8],
                "status": AutopilotJobStatus.SCORED.value,
            }
        else:
            # No Mistral score available (Ollama down, or not preprocessed yet).
            # The full heuristic fallback (per-sentence resume/requirement
            # matching in job_matching.match_job) is expensive enough, run
            # across every unscored candidate in one inline pass, to pin the
            # GIL and freeze the whole API for the length of a large batch
            # (see NIGHT_BATCH_DECISIONS.md, 2026-09-15 17:48 UTC). minMatchScore
            # only orders the queue and never removes anything from it (see
            # below), so an unscored job queues exactly the same as a scored
            # one - skip the expensive evaluation and use a neutral
            # placeholder. Ordering among unscored jobs falls back to
            # tier/recency only (queue_priority_score).
            score = 0.0
            ranked_job = {
                **job,
                "matchScore": score,
                "matchReason": "Not yet scored (local model unavailable).",
                "keyMatchingSkills": [],
                "missingSkills": [],
                "matchMethod": "unscored",
                "matchModel": "",
                "matchReasons": [],
                "status": AutopilotJobStatus.SCORED.value,
            }

        ranked_job["queuePriority"] = queue_priority_score(ranked_job)
        all_passing.append(ranked_job)

        # Mark this candidate as taken immediately, not just on the next call
        # into this function - otherwise the same posting appearing twice in
        # this same raw_jobs batch (a duplicate scrape, not a duplicate DB
        # row) passes the hard filter both times and gets queued twice.
        if not opts.get("allowDuplicates", False):
            dup_key = generate_composite_job_key(
                job.get("company") or "",
                job.get("title") or "",
                job.get("applicationUrl") or job.get("listingUrl") or "",
                job.get("externalJobId") or "",
                job.get("location") or "",
            )
            existing_key_index.setdefault(dup_key, set()).add(AutopilotJobStatus.QUEUED.value)

    # Sort descending by queue priority (tier bonus + match score), then datePosted
    all_passing.sort(key=lambda j: (j.get("queuePriority", 0.0), j.get("datePosted") or ""), reverse=True)

    # minMatchScore orders the queue; it does not remove anything from it.
    #
    # This used to drop every job below the bar whenever at least one job
    # cleared it, which threw away postings for two reasons that are both bad.
    # A job with no score is missing data, not a poor match - when the local
    # model is down or returns unparseable output the score is absent, and
    # filtering on a field that defaults to 0.0 deleted real postings for a
    # reason that had nothing to do with the job. And a genuinely low score is
    # a judgement from a small local model that is often wrong; the user works
    # these lists by hand and may well want to apply anyway.
    #
    # Nothing here weakens the submission bar: a low-scoring job still is not
    # auto-submitted, it just stays visible. Hard eligibility filters above
    # still exclude genuine dead ends.
    if min_score > 0:
        all_passing.sort(
            key=lambda j: (
                float(j.get("matchScore") or 0.0) >= min_score,
                j.get("queuePriority", 0.0),
                j.get("datePosted") or "",
            ),
            reverse=True,
        )

    return all_passing[:max_apps] if max_apps > 0 else all_passing
