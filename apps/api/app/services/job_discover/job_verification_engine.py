"""Job Discovery, Extraction, Verification, Freshness, and Deduplication Subsystem for CareerOS.

Strictly separates DISCOVERY from AUTHORITATIVE VERIFICATION, enforces date provenance,
maps canonical ATS sources, normalizes remote/location/seniority attributes, and deduplicates listings.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from app.services.job_discover.dedup import canonicalize_url, compute_job_fingerprint


class CanonicalSourceType(str, Enum):
    OFFICIAL_CAREERS = "OFFICIAL_CAREERS"
    OFFICIAL_ATS = "OFFICIAL_ATS"
    STRUCTURED_FEED = "STRUCTURED_FEED"
    MAJOR_JOB_BOARD = "MAJOR_JOB_BOARD"
    SEARCH_ENGINE = "SEARCH_ENGINE"
    AGGREGATOR = "AGGREGATOR"


class PostingDateConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNVERIFIED = "UNVERIFIED"


class VerificationStatus(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    UNVERIFIED = "UNVERIFIED"


class JobVerificationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    POSSIBLY_OPEN = "POSSIBLY_OPEN"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class RemoteStatus(str, Enum):
    REMOTE = "REMOTE"
    HYBRID = "HYBRID"
    ONSITE = "ONSITE"
    UNKNOWN = "UNKNOWN"


ATS_DOMAIN_PATTERNS = [
    (r"boards\.greenhouse\.io|job-boards\.greenhouse\.io", "Greenhouse", CanonicalSourceType.OFFICIAL_ATS),
    (r"jobs\.lever\.co", "Lever", CanonicalSourceType.OFFICIAL_ATS),
    (r"jobs\.ashbyhq\.com", "Ashby", CanonicalSourceType.OFFICIAL_ATS),
    (r"myworkdayjobs\.com", "Workday", CanonicalSourceType.OFFICIAL_ATS),
    (r"smartrecruiters\.com", "SmartRecruiters", CanonicalSourceType.OFFICIAL_ATS),
    (r"icims\.com", "iCIMS", CanonicalSourceType.OFFICIAL_ATS),
    (r"jobvite\.com", "Jobvite", CanonicalSourceType.OFFICIAL_ATS),
    (r"oraclecloud\.com|taleo\.net", "Oracle Recruiting", CanonicalSourceType.OFFICIAL_ATS),
    (r"successfactors\.com", "SAP SuccessFactors", CanonicalSourceType.OFFICIAL_ATS),
    (r"eightfold\.ai", "Eightfold", CanonicalSourceType.OFFICIAL_ATS),
    (r"phenompeople\.com", "Phenom", CanonicalSourceType.OFFICIAL_ATS),
]

AGGREGATOR_PATTERNS = [
    (r"linkedin\.com", "LinkedIn", CanonicalSourceType.MAJOR_JOB_BOARD),
    (r"indeed\.com", "Indeed", CanonicalSourceType.MAJOR_JOB_BOARD),
    (r"glassdoor\.com", "Glassdoor", CanonicalSourceType.MAJOR_JOB_BOARD),
    (r"ziprecruiter\.com", "ZipRecruiter", CanonicalSourceType.MAJOR_JOB_BOARD),
    (r"google\.com", "Google Jobs", CanonicalSourceType.SEARCH_ENGINE),
]


def resolve_canonical_source(url: str) -> tuple[CanonicalSourceType, str]:
    """Inspect URL structure to resolve authoritative source tier and name."""
    if not url:
        return CanonicalSourceType.AGGREGATOR, "Unknown Aggregator"

    parsed = urlparse(url.lower())
    domain = parsed.netloc
    path = parsed.path

    for pattern, name, source_tier in ATS_DOMAIN_PATTERNS:
        if re.search(pattern, domain):
            return source_tier, name

    for pattern, name, source_tier in AGGREGATOR_PATTERNS:
        if re.search(pattern, domain):
            return source_tier, name

    if "careers." in domain or "jobs." in domain or "/jobs/" in path or "/careers/" in path or "/job/" in path:
        return CanonicalSourceType.OFFICIAL_CAREERS, f"Official Careers ({domain})"

    return CanonicalSourceType.AGGREGATOR, f"Web Result ({domain})"


def parse_posting_date(date_str: str | None) -> tuple[str | None, PostingDateConfidence]:
    """Strictly distinguish employer posting dates from crawler ingestion timestamps.

    Disregards index/crawl strings like 'indexed 2 days ago' or 'recently updated'.
    """
    if not date_str or not isinstance(date_str, str):
        return None, PostingDateConfidence.UNVERIFIED

    clean_str = date_str.strip()
    lower_str = clean_str.lower()

    # Exclude crawler/indexer relative timestamps
    if any(k in lower_str for k in ("indexed", "crawled", "seen", "viewed", "refreshed", "cached", "ago")):
        return None, PostingDateConfidence.UNVERIFIED

    try:
        dt = datetime.fromisoformat(clean_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat(), PostingDateConfidence.HIGH
    except Exception:
        pass

    # Match YYYY-MM-DD
    match = re.search(r"\b(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b", clean_str)
    if match:
        formatted = f"{match.group(1)}-{match.group(2)}-{match.group(3)}T00:00:00+00:00"
        return formatted, PostingDateConfidence.MEDIUM

    return None, PostingDateConfidence.UNVERIFIED


def detect_remote_status(location_raw: str = "", title: str = "", workplace_type: str = "") -> RemoteStatus:
    combined = f"{location_raw} {title} {workplace_type}".lower()

    if any(k in combined for k in ("remote", "work from home", "virtual", "telecommute", "wfh")):
        return RemoteStatus.REMOTE
    if "hybrid" in combined or "flexible" in combined:
        return RemoteStatus.HYBRID
    if any(k in combined for k in ("on-site", "onsite", "office-based", "in-office")):
        return RemoteStatus.ONSITE

    return RemoteStatus.UNKNOWN


def normalize_seniority(title: str) -> str:
    t = title.lower()
    if "intern" in t or "co-op" in t:
        return "INTERN"
    if "entry" in t or "junior" in t or "associate" in t or "grad" in t:
        return "ENTRY"
    if "principal" in t:
        return "PRINCIPAL"
    if "distinguished" in t or "fellow" in t:
        return "DISTINGUISHED"
    if "senior staff" in t or "sr staff" in t:
        return "SENIOR_STAFF"
    if "staff" in t:
        return "STAFF"
    if "senior" in t or "sr" in t or "lead" in t:
        return "SENIOR"
    if "manager" in t or "head of" in t:
        return "MANAGER"
    if "director" in t:
        return "DIRECTOR"
    if "vp" in t or "vice president" in t:
        return "VP"
    return "MID"


def normalize_title(title: str) -> str:
    t = title.strip()
    # Normalize common level variants while keeping raw title intact
    cleaned = re.sub(r"\b(iii|ii|i|iv|v|level\s*\d+|sr\.?|jr\.?)\b", "", t, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or t


def compute_description_hash(description: str) -> str:
    cleaned = re.sub(r"\s+", " ", description.lower().strip())
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest() if cleaned else ""


def verify_and_normalize_job(raw_job: dict[str, Any], discovery_source: str = "Crawler") -> dict[str, Any]:
    """Execute complete normalization, date provenance separation, and source hierarchy mapping."""
    now_str = datetime.now(timezone.utc).isoformat()

    company = str(raw_job.get("companyName") or raw_job.get("company") or "").strip()
    title = str(raw_job.get("title") or "").strip()
    url = canonicalize_url(raw_job.get("url") or raw_job.get("canonical_job_url") or raw_job.get("applicationUrl") or "")
    apply_url = canonicalize_url(raw_job.get("applyUrl") or raw_job.get("apply_url") or url)

    source_tier, source_name = resolve_canonical_source(url)

    posting_date, date_conf = parse_posting_date(raw_job.get("posting_date") or raw_job.get("datePosted") or raw_job.get("publishedAt"))

    desc = str(raw_job.get("description") or raw_job.get("job_description") or "")
    desc_hash = compute_description_hash(desc)

    remote_stat = detect_remote_status(
        location_raw=str(raw_job.get("location_raw") or raw_job.get("location") or ""),
        title=title,
        workplace_type=str(raw_job.get("workplaceType") or raw_job.get("remote_status") or ""),
    )

    norm_title = normalize_title(title)
    seniority = normalize_seniority(title)

    req_id = str(raw_job.get("requisition_id") or raw_job.get("requisitionId") or raw_job.get("externalJobId") or "").strip()
    fingerprint = compute_job_fingerprint(company, title, str(raw_job.get("location") or ""), url)
    job_id = req_id if req_id else f"job_{fingerprint}"

    existing_disc_sources = raw_job.get("discovery_sources") or [discovery_source]
    if discovery_source not in existing_disc_sources:
        existing_disc_sources.append(discovery_source)

    verif_status = VerificationStatus.FULL.value if source_tier in (CanonicalSourceType.OFFICIAL_CAREERS, CanonicalSourceType.OFFICIAL_ATS) else VerificationStatus.PARTIAL.value

    return {
        "company": company,
        "title": title,
        "normalized_title": norm_title,
        "seniority": seniority,
        "job_id": job_id,
        "requisition_id": req_id,
        "location_raw": str(raw_job.get("location_raw") or raw_job.get("location") or ""),
        "city": raw_job.get("city") or "",
        "state": raw_job.get("state") or "",
        "country": raw_job.get("country") or "US",
        "additional_locations": raw_job.get("additional_locations") or [],
        "remote_status": remote_stat.value,
        "employment_type": raw_job.get("employment_type") or raw_job.get("employmentType") or "Full-time",
        "posting_date": posting_date,
        "posting_date_confidence": date_conf.value,
        "first_seen_date": raw_job.get("first_seen_date") or now_str,
        "last_seen_date": now_str,
        "source_updated_date": raw_job.get("source_updated_date") or now_str,
        "salary_min": raw_job.get("salary_min"),
        "salary_max": raw_job.get("salary_max"),
        "salary_currency": raw_job.get("salary_currency") or "USD",
        "salary_period": raw_job.get("salary_period") or "YEAR",
        "minimum_years_experience": raw_job.get("minimum_years_experience"),
        "preferred_years_experience": raw_job.get("preferred_years_experience"),
        "responsibilities": raw_job.get("responsibilities") or [],
        "minimum_qualifications": raw_job.get("minimum_qualifications") or [],
        "preferred_qualifications": raw_job.get("preferred_qualifications") or [],
        "required_skills": raw_job.get("required_skills") or [],
        "preferred_skills": raw_job.get("preferred_skills") or [],
        "technologies": raw_job.get("technologies") or [],
        "description": desc,
        "description_hash": desc_hash,
        "canonical_job_url": url,
        "apply_url": apply_url,
        "canonical_source": source_name,
        "canonical_source_tier": source_tier.value,
        "discovery_sources": existing_disc_sources,
        "verification_source": source_name,
        "job_status": raw_job.get("job_status") or JobVerificationStatus.OPEN.value,
        "verification_status": verif_status,
        "possible_repost": bool(raw_job.get("possible_repost", False)),
        "verification_timestamp": now_str,
    }
