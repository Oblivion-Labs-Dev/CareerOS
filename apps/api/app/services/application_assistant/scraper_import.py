"""Import jobs from the Job Scraper index into Application Assistant."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import get_kv, list_entities
from app.services.application_assistant.persistence import (
    create_application_draft,
    get_job_match,
    list_discovered_jobs,
    save_job_match,
    upsert_discovered_job,
)
from app.services.application_assistant.url_validation import detect_provider_from_url
from app.services.job_discover import store as jd_store

SCRAPER_DISCOVERY_RUN_ID = "scraper_import"


def is_added_to_assistant(job: dict[str, Any]) -> bool:
    return bool(job.get("addedToAssistant"))


def aa_job_id_for_scraper(scraper_job_id: str) -> str:
    return "aa_" + scraper_job_id.replace(":", "_")


def _content_hash(scraper_job: dict[str, Any]) -> str:
    desc = (scraper_job.get("description") or "")[:500]
    return hashlib.md5(
        f"{scraper_job.get('title', '')}{scraper_job.get('location', '')}{desc}".encode()
    ).hexdigest()


def scraper_job_to_aa_job(scraper_job: dict[str, Any]) -> dict[str, Any]:
    url = scraper_job.get("url") or ""
    location = scraper_job.get("location") or ""
    return {
        "id": aa_job_id_for_scraper(str(scraper_job["id"])),
        "sourceProvider": detect_provider_from_url(url),
        "company": (scraper_job.get("companyName") or "").title(),
        "title": scraper_job.get("title") or "",
        "description": scraper_job.get("description") or "",
        "location": location,
        "workplaceType": "remote" if "remote" in location.lower() else "",
        "applicationUrl": url,
        "listingUrl": url,
        "externalJobId": scraper_job.get("externalId") or "",
        "contentHash": _content_hash(scraper_job),
        "active": True,
        "discoveryRunId": SCRAPER_DISCOVERY_RUN_ID,
        "scraperJobId": scraper_job["id"],
        "scraperRelevancyScore": scraper_job.get("relevancyScore"),
        "scraperKeywordsMatched": scraper_job.get("keywordsMatched") or [],
    }


def import_scraper_job_record(
    db: Session,
    scraper_job: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
    rescore: bool = True,
    mark_added: bool = False,
) -> dict[str, Any]:
    """Upsert one scraper job into aa_discovered_job and optionally refresh match."""
    job_data = scraper_job_to_aa_job(scraper_job)
    existing = next(
        (j for j in list_discovered_jobs(db, active_only=False, exclude_demo=False) if j.get("id") == job_data["id"]),
        None,
    )
    if mark_added or (existing and is_added_to_assistant(existing)):
        job_data["addedToAssistant"] = True
    unchanged = (
        existing
        and existing.get("contentHash") == job_data["contentHash"]
        and existing.get("scraperRelevancyScore") == job_data.get("scraperRelevancyScore")
        and bool(existing.get("addedToAssistant")) == bool(job_data.get("addedToAssistant"))
    )
    saved = upsert_discovered_job(db, job_data)
    match = get_job_match(db, saved["id"])
    if rescore and (not unchanged or not match):
        from app.services.application_assistant.candidate_match_context import match_job_with_context

        profile = profile if profile is not None else (get_kv(db, "profile") or {})
        documents = get_kv(db, "documents") or {}
        accomplishments = list_entities(db, "accomplishment")
        match = match_job_with_context(db, saved, profile, use_qwen=True)
        match = save_job_match(db, match)
        scraper_snapshot_job = next(
            (j for j in (jd_store.get_snapshot(db).get("jobs") or []) if j.get("id") == scraper_job.get("id")),
            scraper_job,
        )
        from app.services.job_discover.gap_analysis import attach_gap_to_job

        profile_hash = jd_store.compute_match_profile_hash(
            profile,
            documents=documents,
            accomplishments=accomplishments,
        )
        enriched = attach_gap_to_job(
            {**scraper_snapshot_job, "relevancyScore": match.get("overallScore", scraper_snapshot_job.get("relevancyScore"))},
            match,
            profile,
            documents=documents,
            accomplishments=accomplishments,
            lightweight=False,
        )
        enriched["gapProfileHash"] = profile_hash
        jd_store._merge_jobs_into_snapshot(db, [enriched])
    if not existing:
        action = "created"
    elif unchanged:
        action = "unchanged"
    else:
        action = "updated"
    return {"job": saved, "match": match, "action": action, "created": action == "created", "updated": action == "updated"}


def ensure_application_draft_for_aa_job(
    db: Session,
    job: dict[str, Any],
    match: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create or reuse the application draft so the job appears in the pipeline queue."""
    if match is None:
        match = get_job_match(db, job.get("id", ""))
    return create_application_draft(
        db,
        {
            "jobId": job["id"],
            "jobUrl": job.get("applicationUrl", job.get("listingUrl", "")),
            "companyName": job.get("company", ""),
            "roleTitle": job.get("title", ""),
            "provider": job.get("sourceProvider", "unknown"),
            "matchScore": match.get("overallScore", 0) if match else 0,
        },
    )


def import_scraper_job_by_id(db: Session, scraper_job_id: str) -> dict[str, Any]:
    snap = jd_store.get_snapshot(db)
    scraper_job = next((j for j in (snap.get("jobs") or []) if j.get("id") == scraper_job_id), None)
    if not scraper_job:
        raise ValueError(f"Scraper job {scraper_job_id} not found")
    result = import_scraper_job_record(db, scraper_job, mark_added=True)
    application = ensure_application_draft_for_aa_job(db, result["job"], result.get("match"))
    return {"success": True, **result, "application": application, "applicationId": application["id"]}


def sync_scraper_jobs(
    db: Session,
    *,
    min_relevancy_score: float = 0,
    limit: int | None = None,
    rescore: bool = False,
) -> dict[str, Any]:
    """Refresh scraper jobs the user already added to Application Assistant."""
    snap = jd_store.get_snapshot(db)
    scraper_by_id = {str(j.get("id")): j for j in (snap.get("jobs") or []) if j.get("id")}
    profile = get_kv(db, "profile") or {}

    added_aa_jobs = [
        j
        for j in list_discovered_jobs(db, active_only=False, exclude_demo=False)
        if is_added_to_assistant(j) and j.get("scraperJobId")
    ]

    if min_relevancy_score > 0:
        added_aa_jobs = [
            j
            for j in added_aa_jobs
            if float(j.get("scraperRelevancyScore") or 0) >= min_relevancy_score
        ]

    added_aa_jobs.sort(key=lambda j: float(j.get("scraperRelevancyScore") or 0), reverse=True)
    if limit is not None and limit > 0:
        added_aa_jobs = added_aa_jobs[:limit]

    created = 0
    updated = 0
    unchanged = 0
    processed = 0
    for aa_job in added_aa_jobs:
        scraper_job = scraper_by_id.get(str(aa_job.get("scraperJobId")))
        if not scraper_job:
            continue
        processed += 1
        result = import_scraper_job_record(
            db,
            scraper_job,
            profile=profile,
            rescore=rescore,
            mark_added=True,
        )
        action = result.get("action", "updated")
        if action == "created":
            created += 1
        elif action == "unchanged":
            unchanged += 1
        else:
            updated += 1

    synced_ids = {
        sid for sid in get_synced_scraper_job_ids(db)
        if sid in scraper_by_id
    }

    return {
        "success": True,
        "processed": processed,
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "scraperTotal": len(snap.get("jobs") or []),
        "syncedTotal": len(synced_ids),
        "lastScrapedAt": snap.get("scrapedAt"),
    }


def scraper_sync_status(db: Session) -> dict[str, Any]:
    snap = jd_store.get_snapshot(db)
    scraper_jobs = snap.get("jobs") or []
    scraper_total = len(scraper_jobs)
    scraper_ids = {str(j.get("id")) for j in scraper_jobs if j.get("id")}
    synced_ids = {sid for sid in get_synced_scraper_job_ids(db) if sid in scraper_ids}
    return {
        "scraperTotal": scraper_total,
        "syncedTotal": len(synced_ids),
        "lastScrapedAt": snap.get("scrapedAt"),
        "pendingSync": max(0, scraper_total - len(synced_ids)),
    }


def get_synced_scraper_job_ids(db: Session) -> set[str]:
    return {
        str(j.get("scraperJobId"))
        for j in list_discovered_jobs(db, active_only=False, exclude_demo=False)
        if is_added_to_assistant(j) and j.get("scraperJobId")
    }
