"""Deterministic deduplication, cross-source provenance, and canonical URL helpers for CareerOS Job Ingestion V2."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from app.services.job_discover.sources.base import SOURCE_QUALITY_TIERS

TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referer", "referrer", "gclid", "fbclid", "msclkid", "source",
    "trk", "gh_jid", "gh_src", "lever-source", "ashby_jid", "sr_source",
    "intcmp", "sub_id", "affiliate", "tracking_code",
})


def canonicalize_url(url: str) -> str:
    """Strip known marketing tracking query parameters while preserving job identifying params."""
    if not url or not isinstance(url, str) or not url.strip():
        return ""

    try:
        clean_input = url.strip()
        parsed = urlparse(clean_input)
        query = parse_qs(parsed.query, keep_blank_values=True)
        clean_query = {k: v for k, v in query.items() if k.lower() not in TRACKING_PARAMS}

        # Reconstruct query
        new_query = urlencode(clean_query, doseq=True)
        clean_url = urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            parsed.params,
            new_query,
            "",  # Strip fragment
        ))
        return clean_url
    except Exception:
        # Fallback for malformed URLs
        return url.strip().split("?")[0].rstrip("/")


def compute_job_fingerprint(company: str, title: str, location: str = "", source_url: str = "") -> str:
    """Generate deterministic SHA256 fingerprint for deduplication."""
    clean_company = re.sub(r"[^\w]", "", company.lower())
    clean_title = re.sub(r"[^\w]", "", title.lower())
    clean_location = re.sub(r"[^\w]", "", location.lower())
    clean_url = canonicalize_url(source_url)

    key = f"{clean_company}:{clean_title}:{clean_location}:{clean_url}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def compute_fuzzy_signature(company: str, title: str, location: str = "", description: str = "") -> str:
    """Generate strong fuzzy signature: normalized company + normalized title + first 300 chars of description."""
    clean_company = re.sub(r"[^\w]", "", company.lower())
    # Strip level qualifiers for title matching: Senior Software Engineer -> software engineer
    clean_title = re.sub(r"\b(senior|sr\.?|junior|jr\.?|staff|principal|lead|ii|iii|iv|v)\b", "", title.lower())
    clean_title = re.sub(r"[^\w]", "", clean_title)

    # Simplified state/country or remote location
    clean_loc = "remote" if "remote" in location.lower() else re.sub(r"[^\w]", "", location.lower()[:30])

    desc_snippet = re.sub(r"\s+", " ", description.lower().strip())[:300]
    desc_hash = hashlib.sha256(desc_snippet.encode("utf-8")).hexdigest()[:12] if desc_snippet else ""

    key = f"{clean_company}:{clean_title}:{clean_loc}:{desc_hash}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


# Location strings that carry no city-level information. When either side of a
# candidate cross-source match reduces to one of these, the two records are
# treated as location-compatible: aggregators routinely flatten a specific
# "San Francisco, CA" posting down to "USA" or "Remote".
_GENERIC_LOCATIONS = frozenset({
    "", "remote", "remoteus", "remoteusa", "us", "usa", "unitedstates",
    "unitedstatesofamerica", "anywhere", "worldwide", "global", "multiple",
    "multiplelocations", "various", "variouslocations", "flexible",
})


def _location_bucket(location: str) -> str:
    """Reduce a location to a comparable token, or "" when uninformative."""
    if not location:
        return ""
    loc = location.lower()
    # "Remote (USA)" / "Remote - San Francisco, CA" → drop the remote wrapper
    # and keep whatever geography remains, so a remote posting can still match
    # the same posting listed with its office city.
    loc = re.sub(r"\b(remote|hybrid|onsite|on-site|work from home|wfh)\b", " ", loc)
    loc = re.sub(r"[^\w\s,]", " ", loc)
    head = loc.split(",")[0]
    token = re.sub(r"[^\w]", "", head)
    if token in _GENERIC_LOCATIONS:
        return ""
    return token[:20]


def locations_compatible(a: str, b: str) -> bool:
    """Whether two location strings could describe the same posting."""
    bucket_a, bucket_b = _location_bucket(a), _location_bucket(b)
    if not bucket_a or not bucket_b:
        return True
    return bucket_a == bucket_b


def compute_cross_source_key(company: str, title: str) -> str:
    """Identity key for matching the SAME posting across DIFFERENT sources.

    Deliberately excludes URL and description — the two fields that always
    differ between an ATS board and an aggregator that relists it. Jobicy
    truncates the description and rewrites the link, so compute_fuzzy_signature
    (which hashes the first 300 description chars) can never match across
    sources; that is why the same role appeared twice in the index.

    Because this key is coarse, callers must only use it to merge records whose
    sources differ AND whose locations are compatible. Two same-source postings
    sharing a company and title are usually two genuine requisitions.
    """
    clean_company = re.sub(r"[^\w]", "", company.lower())
    clean_title = re.sub(
        r"\b(senior|sr\.?|junior|jr\.?|staff|principal|lead|i|ii|iii|iv|v)\b", "", title.lower()
    )
    clean_title = re.sub(r"[^\w]", "", clean_title)
    if not clean_company or not clean_title:
        return ""
    return hashlib.sha256(f"{clean_company}:{clean_title}".encode("utf-8")).hexdigest()[:16]


def source_label(job: dict[str, Any]) -> str:
    """Best available provenance label for a job record."""
    return str(job.get("source") or job.get("canonicalSource") or "").strip().lower()


def get_source_priority(job: dict[str, Any]) -> int:
    """Determine integer priority tier (100 highest -> 40 lowest) for a job record."""
    if job.get("sourcePriority") is not None:
        return int(job["sourcePriority"])
    if job.get("sourceQuality") is not None:
        return int(job["sourceQuality"])

    s_type = str(job.get("sourceType") or "").lower()
    if s_type in SOURCE_QUALITY_TIERS:
        return SOURCE_QUALITY_TIERS[s_type]

    s_name = str(job.get("source") or "").lower()
    if any(k in s_name for k in ("greenhouse", "lever", "ashby", "workday", "smartrecruiters", "workable", "oracle", "icims")):
        return SOURCE_QUALITY_TIERS["ats"]
    if any(k in s_name for k in ("google_careers", "apple", "meta", "amazon", "microsoft", "netflix")):
        return SOURCE_QUALITY_TIERS["company_api"]
    if any(k in s_name for k in ("jobicy", "arbeitnow", "remotive")):
        return SOURCE_QUALITY_TIERS["public_api"]
    if "hackernews" in s_name or "hn" in s_name:
        return SOURCE_QUALITY_TIERS["community"]
    if "github" in s_name:
        return SOURCE_QUALITY_TIERS["github_feed"]
    if "google_jobs" in s_name or "serpapi" in s_name:
        return SOURCE_QUALITY_TIERS["aggregator"]

    return SOURCE_QUALITY_TIERS["scraper"]


def merge_job_records(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge duplicate job records respecting source hierarchy and accumulating provenance references.

    Priority hierarchy:
      direct employer (100) > ATS (95) > curated public API (80) > community/feed (70) > aggregator (60) > scraper (40)
    Higher tier wins primary fields. Lower tier records enrich non-conflicting metadata and append provenance.
    """
    exist_prio = get_source_priority(existing)
    incom_prio = get_source_priority(incoming)

    # Union provenance sources
    disc_sources: list[str] = []
    for s in (existing.get("discoverySources") or []):
        if s and s not in disc_sources:
            disc_sources.append(s)
    for s in (incoming.get("discoverySources") or []):
        if s and s not in disc_sources:
            disc_sources.append(s)

    # Both records' own source labels count as provenance. Only the incoming
    # one used to be recorded, so when a lower-priority record was displaced as
    # the base its origin vanished from the merged job's provenance.
    for own_src in (existing.get("source"), incoming.get("source")):
        if own_src and own_src not in disc_sources:
            disc_sources.append(own_src)

    # Date provenance: retain earliest firstSeenDate, latest lastSeenDate
    first_seen = existing.get("firstSeenDate") or existing.get("first_seen_at")
    inc_first_seen = incoming.get("firstSeenDate") or incoming.get("first_seen_at")
    if inc_first_seen and (not first_seen or inc_first_seen < first_seen):
        first_seen = inc_first_seen

    now_iso = datetime.now(UTC).isoformat()
    last_seen = now_iso

    # If incoming has strictly higher priority, incoming becomes base
    if incom_prio > exist_prio:
        merged = dict(incoming)
        # Inherit historical values
        merged["firstSeenDate"] = first_seen
        merged["first_seen_at"] = first_seen
        merged["lastSeenDate"] = last_seen
        merged["last_seen_at"] = last_seen
        merged["discoverySources"] = disc_sources
        # Retain relevancy score if already scored
        if not merged.get("relevancyScore") and existing.get("relevancyScore"):
            merged["relevancyScore"] = existing["relevancyScore"]
            merged["keywordsMatched"] = existing.get("keywordsMatched") or []
            merged["color"] = existing.get("color", "gray")
        # Retain user interaction states
        if existing.get("addedToAssistant"):
            merged["addedToAssistant"] = True
        return merged
    else:
        merged = dict(existing)
        merged["firstSeenDate"] = first_seen
        merged["first_seen_at"] = first_seen
        merged["lastSeenDate"] = last_seen
        merged["last_seen_at"] = last_seen
        merged["discoverySources"] = disc_sources

        # Enrich empty fields from incoming
        if not merged.get("description") and incoming.get("description"):
            merged["description"] = incoming["description"]
        if not merged.get("salaryRange") and incoming.get("salaryRange"):
            merged["salaryRange"] = incoming["salaryRange"]
            merged["salary_range"] = incoming["salaryRange"]
        if not merged.get("salaryMin") and incoming.get("salaryMin"):
            merged["salaryMin"] = incoming["salaryMin"]
            merged["salaryMax"] = incoming.get("salaryMax")
        if not merged.get("applyUrl") and incoming.get("applyUrl"):
            merged["applyUrl"] = incoming["applyUrl"]
        if incoming.get("sponsorshipMention"):
            merged["sponsorshipMention"] = True
            if incoming.get("sponsorshipStatus"):
                merged["sponsorshipStatus"] = incoming["sponsorshipStatus"]

        return merged


class DedupeIndex:
    """The lookup tables cross_source_deduplicate builds, kept across calls.

    A scrape used to call cross_source_deduplicate(existing + incoming) once per
    board batch. With 638 batches over a 3,400-job corpus that rebuilt every
    index from scratch 638 times and re-fingerprinted the whole corpus each
    time - O(batches x corpus). It is the single reason a scrape that takes 43
    seconds in memory took about twelve minutes when persisted.

    Holding the index and feeding it only the new batch makes the same work
    O(corpus + total_incoming). The matching rules are unchanged: `add` is the
    body of the original loop, so both entry points share one implementation.
    """

    __slots__ = ("by_id", "url_to_id", "req_to_id", "fuzzy_to_id", "coarse_to_ids", "order")

    def __init__(self) -> None:
        self.by_id: dict[str, dict[str, Any]] = {}
        self.url_to_id: dict[str, str] = {}
        self.req_to_id: dict[str, str] = {}
        self.fuzzy_to_id: dict[str, str] = {}
        self.coarse_to_ids: dict[str, list[str]] = {}
        self.order: list[str] = []

    def extend(self, jobs: list[dict[str, Any]]) -> None:
        for job in jobs:
            self.add(job)

    def values(self) -> list[dict[str, Any]]:
        """Surviving records, in the order they were first seen."""
        return [self.by_id[key] for key in self.order if key in self.by_id]

    def add(self, job: dict[str, Any]) -> None:
        by_id = self.by_id
        url_to_id = self.url_to_id
        req_to_id = self.req_to_id
        fuzzy_to_id = self.fuzzy_to_id
        coarse_to_ids = self.coarse_to_ids

        raw_id = job.get("id") or compute_job_fingerprint(
            job.get("companyName") or job.get("company", ""),
            job.get("title", ""),
            job.get("location", ""),
            job.get("url", ""),
        )
        url = canonicalize_url(job.get("canonicalUrl") or job.get("url", ""))
        comp = (job.get("companyName") or job.get("company", "")).strip().lower()
        req_id = str(job.get("requisition_id") or job.get("externalId") or job.get("greenhouse_id") or "").strip()
        req_key = f"{comp}:{req_id}" if comp and req_id else ""

        fuzzy_sig = compute_fuzzy_signature(
            comp,
            job.get("title", ""),
            job.get("location", ""),
            job.get("description", ""),
        )
        coarse_key = compute_cross_source_key(comp, job.get("title", ""))
        job_source = source_label(job)

        matched_id: str | None = None

        # 1. Exact ID match
        if raw_id in by_id:
            matched_id = raw_id
        # 2. Canonical URL match
        elif url and url in url_to_id:
            matched_id = url_to_id[url]
        # 3. Requisition ID + Company match
        elif req_key and req_key in req_to_id:
            matched_id = req_to_id[req_key]
        # 4. Fuzzy signature match
        elif fuzzy_sig and fuzzy_sig in fuzzy_to_id:
            matched_id = fuzzy_to_id[fuzzy_sig]
        # 5. Cross-source match: same company and title, compatible location,
        #    but a DIFFERENT source.
        elif coarse_key and job_source:
            for candidate_id in coarse_to_ids.get(coarse_key, []):
                candidate = by_id.get(candidate_id)
                if candidate is None:
                    continue
                if source_label(candidate) == job_source:
                    continue
                if not locations_compatible(candidate.get("location", ""), job.get("location", "")):
                    continue
                matched_id = candidate_id
                break

        if matched_id and matched_id in by_id:
            by_id[matched_id] = merge_job_records(by_id[matched_id], job)
        else:
            job["id"] = raw_id
            if url:
                job["canonicalUrl"] = url
                job["url"] = url
            by_id[raw_id] = job
            matched_id = raw_id
            self.order.append(raw_id)

        if url:
            url_to_id[url] = matched_id
        if req_key:
            req_to_id[req_key] = matched_id
        if fuzzy_sig:
            fuzzy_to_id[fuzzy_sig] = matched_id
        if coarse_key:
            bucket = coarse_to_ids.setdefault(coarse_key, [])
            if matched_id not in bucket:
                bucket.append(matched_id)


def cross_source_deduplicate(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate job list using multi-index deterministic matching (exact ID, canonical URL, requisition, fuzzy)."""
    index = DedupeIndex()
    index.extend(jobs)
    return index.values()


def _legacy_cross_source_deduplicate(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The original single-pass implementation, kept as a differential oracle.

    tests/test_dedupe_index_equivalence.py asserts the incremental index agrees
    with this on real corpus data, so the optimisation cannot drift from the
    behaviour it replaced without a test failing.
    """
    by_id: dict[str, dict[str, Any]] = {}
    url_to_id: dict[str, str] = {}
    req_to_id: dict[str, str] = {}
    fuzzy_to_id: dict[str, str] = {}
    # company+title -> candidate ids, used only for cross-source matching.
    coarse_to_ids: dict[str, list[str]] = {}

    for job in jobs:
        raw_id = job.get("id") or compute_job_fingerprint(
            job.get("companyName") or job.get("company", ""),
            job.get("title", ""),
            job.get("location", ""),
            job.get("url", ""),
        )
        url = canonicalize_url(job.get("canonicalUrl") or job.get("url", ""))
        comp = (job.get("companyName") or job.get("company", "")).strip().lower()
        req_id = str(job.get("requisition_id") or job.get("externalId") or job.get("greenhouse_id") or "").strip()
        req_key = f"{comp}:{req_id}" if comp and req_id else ""

        fuzzy_sig = compute_fuzzy_signature(
            comp,
            job.get("title", ""),
            job.get("location", ""),
            job.get("description", ""),
        )
        coarse_key = compute_cross_source_key(comp, job.get("title", ""))
        job_source = source_label(job)

        matched_id: str | None = None

        # 1. Exact ID match
        if raw_id in by_id:
            matched_id = raw_id
        # 2. Canonical URL match
        elif url and url in url_to_id:
            matched_id = url_to_id[url]
        # 3. Requisition ID + Company match
        elif req_key and req_key in req_to_id:
            matched_id = req_to_id[req_key]
        # 4. Fuzzy signature match
        elif fuzzy_sig and fuzzy_sig in fuzzy_to_id:
            matched_id = fuzzy_to_id[fuzzy_sig]
        # 5. Cross-source match: same company and title, compatible location,
        #    but a DIFFERENT source. This is the aggregator case — the same
        #    Greenhouse posting relisted on Jobicy, Himalayas, WeWorkRemotely
        #    or Hacker News under a different URL and a rewritten description,
        #    which no earlier index can catch. Restricted to differing sources
        #    so two genuine same-board requisitions are never collapsed.
        elif coarse_key and job_source:
            for candidate_id in coarse_to_ids.get(coarse_key, []):
                candidate = by_id.get(candidate_id)
                if candidate is None:
                    continue
                if source_label(candidate) == job_source:
                    continue
                if not locations_compatible(candidate.get("location", ""), job.get("location", "")):
                    continue
                matched_id = candidate_id
                break

        if matched_id and matched_id in by_id:
            existing_job = by_id[matched_id]
            merged_job = merge_job_records(existing_job, job)
            by_id[matched_id] = merged_job
        else:
            job["id"] = raw_id
            if url:
                job["canonicalUrl"] = url
                job["url"] = url
            by_id[raw_id] = job
            matched_id = raw_id

        # Update lookup indices
        if url:
            url_to_id[url] = matched_id
        if req_key:
            req_to_id[req_key] = matched_id
        if fuzzy_sig:
            fuzzy_to_id[fuzzy_sig] = matched_id
        if coarse_key:
            bucket = coarse_to_ids.setdefault(coarse_key, [])
            if matched_id not in bucket:
                bucket.append(matched_id)

    return list(by_id.values())


def deduplicate_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Backward-compatible entry point calling cross_source_deduplicate."""
    return cross_source_deduplicate(jobs)
