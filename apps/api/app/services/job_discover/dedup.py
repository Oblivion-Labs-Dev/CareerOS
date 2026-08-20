"""Deterministic deduplication and canonical URL helpers for CareerOS jobs."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referer", "referrer", "gclid", "fbclid", "msclkid", "source",
    "trk", "gh_jid", "gh_src", "lever-source", "ashby_jid",
})


def canonicalize_url(url: str) -> str:
    """Strip known marketing tracking query parameters while preserving job identifying params."""
    if not url or not url.strip():
        return ""

    parsed = urlparse(url.strip())
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


def compute_job_fingerprint(company: str, title: str, location: str = "", source_url: str = "") -> str:
    """Generate deterministic SHA256 fingerprint for deduplication."""
    clean_company = re.sub(r"[^\w]", "", company.lower())
    clean_title = re.sub(r"[^\w]", "", title.lower())
    clean_location = re.sub(r"[^\w]", "", location.lower())
    clean_url = canonicalize_url(source_url)

    key = f"{clean_company}:{clean_title}:{clean_location}:{clean_url}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def deduplicate_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate job list prioritizing deterministic primary ID and canonical URLs."""
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    deduped: list[dict[str, Any]] = []

    for job in jobs:
        job_id = job.get("id") or compute_job_fingerprint(
            job.get("companyName") or job.get("company", ""),
            job.get("title", ""),
            job.get("location", ""),
            job.get("url", ""),
        )
        url = canonicalize_url(job.get("url", ""))

        if job_id in seen_ids:
            continue
        if url and url in seen_urls:
            continue

        seen_ids.add(job_id)
        if url:
            seen_urls.add(url)

        job["id"] = job_id
        if url:
            job["url"] = url
        deduped.append(job)

    return deduped
