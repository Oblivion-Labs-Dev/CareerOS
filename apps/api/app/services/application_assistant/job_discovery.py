"""Job discovery service with provider-adapter interface."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import get_kv, now_iso, session_scope
from app.services.application_assistant.job_matching import match_job
from app.services.application_assistant.log_redaction import create_log_entry, sanitize_url
from app.services.application_assistant.persistence import (
    append_discovery_log,
    get_discovery_run,
    list_discovered_jobs,
    save_job_match,
    update_discovery_run,
    upsert_discovered_job,
)
from app.services.application_assistant.providers import detect_provider
from app.services.application_assistant.url_validation import normalize_url, validate_url


class DiscoveryCancelled(Exception):
    pass


_active_runs: dict[str, asyncio.Event] = {}


def cancel_discovery(run_id: str) -> bool:
    event = _active_runs.get(run_id)
    if event:
        event.set()
        return True
    return False


async def run_discovery(run_id: str) -> dict[str, Any]:
    """Execute a job discovery run using its own DB session."""
    with session_scope() as db:
        return await _run_discovery_with_session(db, run_id)


async def _run_discovery_with_session(db: Session, run_id: str) -> dict[str, Any]:
    """Execute a job discovery run."""
    run = get_discovery_run(db, run_id)
    if not run:
        return {"success": False, "error": "Discovery run not found"}

    careers_url = run.get("careersUrl", "")
    valid, reason = validate_url(careers_url)
    if not valid:
        update_discovery_run(db, run_id, {
            "status": "failed",
            "error": {"category": "invalid_url", "message": reason},
            "completedAt": now_iso(),
        })
        return {"success": False, "error": reason}

    cancel_event = asyncio.Event()
    _active_runs[run_id] = cancel_event

    update_discovery_run(db, run_id, {"status": "running"})
    append_discovery_log(db, run_id, create_log_entry("discovery_started", details={"url": sanitize_url(careers_url)}))

    provider_name, adapter, supported = detect_provider(careers_url)
    update_discovery_run(db, run_id, {"provider": provider_name})

    if not supported or not adapter:
        msg = f"Provider '{provider_name}' is not supported for job discovery"
        update_discovery_run(db, run_id, {
            "status": "failed",
            "error": {"category": "unsupported_provider", "message": msg},
            "completedAt": now_iso(),
        })
        append_discovery_log(db, run_id, create_log_entry("discovery_failed", details={"reason": msg}))
        _active_runs.pop(run_id, None)
        return {"success": False, "error": msg}

    try:
        from app.services.application_assistant.browser_runner import BrowserSession

        profile = get_kv(db, "profile") or {}
        jobs_found = 0

        async with BrowserSession(headed=False) as session:
            page = await session.new_page()
            append_discovery_log(db, run_id, create_log_entry("navigating", details={"url": sanitize_url(careers_url)}))

            await page.goto(careers_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)  # Allow dynamic content

            if cancel_event.is_set():
                raise DiscoveryCancelled()

            listings = await adapter.discover_jobs(page)
            append_discovery_log(db, run_id, create_log_entry("jobs_extracted", details={"count": len(listings)}))

            existing_jobs = list_discovered_jobs(db, active_only=False)
            existing_urls = {normalize_url(j.get("listingUrl", "")) for j in existing_jobs}

            for listing in listings:
                if cancel_event.is_set():
                    raise DiscoveryCancelled()

                norm_url = normalize_url(listing.listing_url or listing.application_url)
                content_hash = hashlib.md5(
                    f"{listing.title}{listing.location}{listing.description[:500]}".encode()
                ).hexdigest()

                job_data = {
                    "sourceProvider": provider_name,
                    "company": listing.company,
                    "title": listing.title,
                    "description": listing.description,
                    "location": listing.location,
                    "workplaceType": listing.workplace_type,
                    "applicationUrl": listing.application_url,
                    "listingUrl": listing.listing_url or listing.application_url,
                    "externalJobId": listing.external_job_id,
                    "salaryMin": listing.salary_min,
                    "salaryMax": listing.salary_max,
                    "currency": listing.currency,
                    "contentHash": content_hash,
                    "active": True,
                    "discoveryRunId": run_id,
                    "dateDiscovered": now_iso(),
                }

                # Deduplicate
                if norm_url in existing_urls:
                    for existing in existing_jobs:
                        if normalize_url(existing.get("listingUrl", "")) == norm_url:
                            if existing.get("contentHash") != content_hash:
                                job_data["id"] = existing["id"]
                                upsert_discovered_job(db, job_data)
                            break
                    continue

                saved_job = upsert_discovered_job(db, job_data)
                existing_urls.add(norm_url)

                from app.services.application_assistant.candidate_match_context import match_job_with_context_async

                match_result = await match_job_with_context_async(
                    db,
                    saved_job,
                    profile,
                    location_preferences=run.get("locationPreferences"),
                    workplace_preference=run.get("workplacePreference", ""),
                )
                save_job_match(db, match_result)
                jobs_found += 1

                # Rate limit
                await asyncio.sleep(0.5)

        update_discovery_run(db, run_id, {
            "status": "completed",
            "jobsFound": jobs_found,
            "completedAt": now_iso(),
        })
        append_discovery_log(db, run_id, create_log_entry("discovery_completed", details={"jobsFound": jobs_found}))

        return {"success": True, "jobsFound": jobs_found}

    except DiscoveryCancelled:
        update_discovery_run(db, run_id, {
            "status": "cancelled",
            "completedAt": now_iso(),
        })
        append_discovery_log(db, run_id, create_log_entry("discovery_cancelled"))
        return {"success": False, "error": "Discovery cancelled"}

    except Exception as exc:
        update_discovery_run(db, run_id, {
            "status": "failed",
            "error": {"category": "network_failure", "message": str(exc)},
            "completedAt": now_iso(),
        })
        append_discovery_log(db, run_id, create_log_entry("discovery_failed", details={"error": str(exc)}))
        return {"success": False, "error": str(exc)}

    finally:
        _active_runs.pop(run_id, None)


def filter_jobs(
    jobs: list[dict[str, Any]],
    matches: dict[str, dict[str, Any]],
    *,
    min_match_score: float = 0,
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter and rank discovered jobs."""
    results = []
    for job in jobs:
        job_id = job.get("id", "")
        match = matches.get(job_id, {})
        score = match.get("overallScore", 0)

        if score < min_match_score:
            continue

        title_lower = job.get("title", "").lower()
        desc_lower = job.get("description", "").lower()

        if include_keywords:
            if not any(kw.lower() in title_lower or kw.lower() in desc_lower for kw in include_keywords):
                continue

        if exclude_keywords:
            if any(kw.lower() in title_lower or kw.lower() in desc_lower for kw in exclude_keywords):
                continue

        results.append({**job, "match": match})

    results.sort(key=lambda j: j.get("match", {}).get("overallScore", 0), reverse=True)
    return results
