"""Job Freshness & Closed Job Detection Lifecycle for CareerOS Job Ingestion V2 (Phase 12).

Tracks posting longevity, detects delisted openings, enforces graceful state transitions:
ACTIVE -> POSSIBLY_CLOSED -> CLOSED,
and provides live URL verification without closing listings on transient provider outages.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger("career_os.job_discover.freshness")

STATUS_ACTIVE = "ACTIVE"
STATUS_POSSIBLY_CLOSED = "POSSIBLY_CLOSED"
STATUS_CLOSED = "CLOSED"

# Consecutive missing syncs from healthy authoritative source before transitioning
THRESHOLD_POSSIBLY_CLOSED = 1
THRESHOLD_CLOSED = 3

CLOSED_TEXT_PATTERNS = [
    r"this job (is no longer available|has expired|has been closed|has been filled)",
    r"this position (is no longer available|has been filled|is closed)",
    r"no longer accepting applications",
    r"posting has expired",
    r"job no longer exists",
    r"the page you are looking for no longer exists",
]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def enrich_freshness_fields(job: dict[str, Any]) -> dict[str, Any]:
    """Ensure baseline freshness fields exist on job record."""
    now = _utc_now_iso()
    result = dict(job)
    if not result.get("firstSeenAt"):
        result["firstSeenAt"] = result.get("firstSeenDate") or result.get("scrapedAt") or now
    if not result.get("lastSeenAt"):
        result["lastSeenAt"] = result.get("lastSeenDate") or now
    if not result.get("lastSuccessfulSourceCheck"):
        result["lastSuccessfulSourceCheck"] = now
    if "missingConsecutiveRuns" not in result:
        result["missingConsecutiveRuns"] = 0
    if not result.get("jobStatus"):
        result["jobStatus"] = STATUS_ACTIVE
    return result


def update_jobs_lifecycle_after_sync(
    existing_jobs: list[dict[str, Any]],
    synced_jobs: list[dict[str, Any]],
    provider_name: str,
    company: str | None = None,
    sync_succeeded: bool = True,
) -> list[dict[str, Any]]:
    """Update job lifecycle based on authoritative sync results.

    Rule: If the provider sync failed, NEVER mark jobs as missing or closed.
    Rule: A single disappearance marks POSSIBLY_CLOSED; 3 consecutive missing syncs mark CLOSED.
    """
    if not sync_succeeded:
        logger.info("Sync failed for %s (%s); skipping freshness state mutation", provider_name, company)
        return existing_jobs

    now = _utc_now_iso()
    synced_ids = {
        str(j.get("id") or j.get("externalId") or j.get("url") or "")
        for j in synced_jobs
        if str(j.get("id") or j.get("externalId") or j.get("url") or "")
    }

    updated_list: list[dict[str, Any]] = []

    for item in existing_jobs:
        job = enrich_freshness_fields(item)
        job_provider = str(job.get("canonicalSource") or "").lower()
        job_company = str(job.get("companyName") or job.get("company") or "").strip().lower()

        # Check if job belongs to the provider/company that was just synced
        matches_provider = (
            provider_name.lower() in job_provider
            or any(provider_name.lower() in str(s).lower() for s in (job.get("discoverySources") or []))
        )
        matches_comp = (not company) or (job_company == company.lower())

        if not (matches_provider and matches_comp):
            # Not affected by this specific provider/company sync run
            updated_list.append(job)
            continue

        job_key = str(job.get("id") or job.get("externalId") or job.get("url") or "")
        is_in_sync = job_key in synced_ids

        if is_in_sync:
            job["lastSeenAt"] = now
            job["lastSuccessfulSourceCheck"] = now
            job["missingConsecutiveRuns"] = 0
            job["jobStatus"] = STATUS_ACTIVE
            job["closedAt"] = None
        else:
            missing = int(job.get("missingConsecutiveRuns", 0)) + 1
            job["missingConsecutiveRuns"] = missing
            job["lastSuccessfulSourceCheck"] = now

            if missing >= THRESHOLD_CLOSED:
                job["jobStatus"] = STATUS_CLOSED
                if not job.get("closedAt"):
                    job["closedAt"] = now
            elif missing >= THRESHOLD_POSSIBLY_CLOSED:
                job["jobStatus"] = STATUS_POSSIBLY_CLOSED

        updated_list.append(job)

    return updated_list


async def check_job_url_freshness(
    url: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Actively verify live job URL freshness with HTTP semantics."""
    if not url:
        return {"status": STATUS_CLOSED, "closed": True, "reason": "Empty URL"}

    local_client = client or httpx.AsyncClient(
        headers={"User-Agent": "CareerOS-JobFreshness/2.0"},
        follow_redirects=True,
        timeout=10.0,
    )

    try:
        # Try HEAD first for minimal payload
        resp = await local_client.head(url)
        if resp.status_code in {404, 410}:
            return {
                "status": STATUS_CLOSED,
                "closed": True,
                "statusCode": resp.status_code,
                "reason": f"HTTP {resp.status_code} Not Found",
            }

        # If HEAD not allowed or inconclusive, perform GET
        if resp.status_code in {405, 403} or resp.is_success:
            resp = await local_client.get(url)
            if resp.status_code in {404, 410}:
                return {
                    "status": STATUS_CLOSED,
                    "closed": True,
                    "statusCode": resp.status_code,
                    "reason": f"HTTP {resp.status_code} Not Found",
                }

            body_text = resp.text.lower()
            for pattern in CLOSED_TEXT_PATTERNS:
                if re.search(pattern, body_text):
                    return {
                        "status": STATUS_CLOSED,
                        "closed": True,
                        "statusCode": resp.status_code,
                        "reason": f"Page content indicates closed: '{pattern}'",
                    }

            return {
                "status": STATUS_ACTIVE,
                "closed": False,
                "statusCode": resp.status_code,
                "reason": "URL verified active",
            }

        return {
            "status": STATUS_ACTIVE,
            "closed": False,
            "statusCode": resp.status_code,
            "reason": f"HTTP {resp.status_code}",
        }
    except Exception as exc:
        # Network errors should NOT close a job
        return {
            "status": STATUS_ACTIVE,
            "closed": False,
            "error": str(exc),
            "reason": "Network or connection error during check",
        }
    finally:
        if client is None:
            await local_client.aclose()
