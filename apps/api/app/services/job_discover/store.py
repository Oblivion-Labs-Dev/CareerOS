"""Job discovery storage, scraping orchestration, and relevancy scoring."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.db.store import get_kv, session_scope, set_kv, upsert_entity
from app.services.job_discover import apify_service, bigtech_scrapers, relevancy_engine, scraper_service
from app.services.job_discover.h1b_sponsorship import apply_h1b_fields

KV_KEY = "job_discover"
DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "job_discover"
SNAPSHOT_FILE = DATA_DIR / "jobs_snapshot.json"

SortOption = Literal["relevancy", "date", "company"]
FreshnessOption = Literal["24", "48", "168", "720", "all"]
ScrapeMode = Literal["ats", "bigtech", "apify", "all"]

# Hard cap: never scrape or retain jobs older than 30 days.
MAX_SCRAPE_HOURS = 720

_scrape_lock = asyncio.Lock()
_save_lock = asyncio.Lock()
_scrape_status: dict[str, Any] = {
    "running": False,
    "progress": "",
    "lastResult": "",
    "lastScrapedAt": None,
    "indexedJobs": 0,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp_scrape_hours(hours: int) -> int:
    """Restrict scrape window to at most the last 30 days."""
    return max(1, min(int(hours), MAX_SCRAPE_HOURS))


def _job_within_retention(job: dict[str, Any], max_hours: int = MAX_SCRAPE_HOURS) -> bool:
    updated = relevancy_engine.compute_freshness(job.get("updatedAt", ""))
    if updated.get("hours_ago", 999) <= max_hours:
        return True
    scraped = relevancy_engine.compute_freshness(job.get("scrapedAt", ""))
    return scraped.get("hours_ago", 999) <= max_hours


def _prune_stale_jobs(jobs: list[dict[str, Any]], max_hours: int = MAX_SCRAPE_HOURS) -> list[dict[str, Any]]:
    return [job for job in jobs if _job_within_retention(job, max_hours)]


def _job_key(job: dict[str, Any]) -> str:
    external = str(job.get("greenhouse_id") or job.get("externalId") or "").strip()
    company = str(job.get("company") or job.get("companyName") or "").strip().lower()
    if external and company:
        return f"{company}:{external}"
    url = str(job.get("url") or "").strip()
    if url:
        return hashlib.sha256(url.encode()).hexdigest()[:16]
    title = str(job.get("title") or "")
    return hashlib.sha256(f"{company}:{title}".encode()).hexdigest()[:16]


def _normalize_scraped_job(raw: dict[str, Any]) -> dict[str, Any]:
    job = {
        "id": _job_key(raw),
        "externalId": str(raw.get("greenhouse_id") or ""),
        "companyName": str(raw.get("company") or "").strip(),
        "title": str(raw.get("title") or "").strip(),
        "location": str(raw.get("location") or "").strip(),
        "department": str(raw.get("department") or "").strip(),
        "url": str(raw.get("url") or "").strip(),
        "description": str(raw.get("description") or "").strip(),
        "updatedAt": str(raw.get("updated_at") or raw.get("updatedAt") or ""),
        "employmentType": str(raw.get("employment_type") or raw.get("employmentType") or ""),
        "salaryRange": str(raw.get("salary_range") or raw.get("salaryRange") or ""),
        "scrapedAt": _utc_now(),
        "relevancyScore": 0,
        "keywordsMatched": [],
        "color": "gray",
    }
    return apply_h1b_fields(job)


def _profile_for_scoring(profile: dict[str, Any] | None) -> dict[str, Any]:
    if not profile:
        return {}
    return {
        "current_title": profile.get("currentTitle") or profile.get("current_title") or profile.get("headline") or "",
        "skills": profile.get("skills") or "",
        "years_experience": profile.get("yearsExperience") or profile.get("years_experience") or 0,
        "city": profile.get("city") or "",
        "state": profile.get("state") or profile.get("region") or "",
    }


def _score_jobs(jobs: list[dict[str, Any]], profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    scoring_profile = _profile_for_scoring(profile)
    scored: list[dict[str, Any]] = []
    for job in jobs:
        result = relevancy_engine.score_job(
            {
                "title": job.get("title", ""),
                "description": job.get("description", ""),
                "location": job.get("location", ""),
                "department": job.get("department", ""),
            },
            scoring_profile,
        )
        scored.append(
            apply_h1b_fields(
                {
                    **job,
                    "relevancyScore": result.get("relevancy_score", 0),
                    "keywordsMatched": result.get("keywords_matched", []),
                    "color": result.get("color", "gray"),
                }
            )
        )
    return scored


def _merge_jobs(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {job["id"]: job for job in existing if job.get("id")}
    for job in incoming:
        by_id[job["id"]] = job
    return list(by_id.values())


def _read_snapshot_file() -> dict[str, Any] | None:
    if not SNAPSHOT_FILE.exists():
        return None
    try:
        payload = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _write_snapshot_file(snapshot: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")


def _persist_snapshot(db: Session, snapshot: dict[str, Any]) -> None:
    set_kv(db, KV_KEY, snapshot)
    _write_snapshot_file(snapshot)


def _load_snapshot(db: Session) -> dict[str, Any]:
    snapshot = get_kv(db, KV_KEY)
    if snapshot and snapshot.get("jobs"):
        jobs = _prune_stale_jobs(snapshot.get("jobs") or [])
        if len(jobs) != len(snapshot.get("jobs") or []):
            snapshot = {**snapshot, "jobs": jobs}
            _persist_snapshot(db, snapshot)
        if not SNAPSHOT_FILE.exists():
            _write_snapshot_file(snapshot)
        return snapshot
    file_snapshot = _read_snapshot_file()
    if file_snapshot and file_snapshot.get("jobs"):
        _persist_snapshot(db, file_snapshot)
        return file_snapshot
    return snapshot or {"jobs": []}


async def _append_scraped_batch(
    db: Session,
    raw_batch: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    hours: int,
    roles: str,
) -> None:
    if not raw_batch:
        return
    async with _save_lock:
        normalized = [_normalize_scraped_job(job) for job in raw_batch]
        scored = _score_jobs(normalized, profile)
        snapshot = _load_snapshot(db)
        merged = _prune_stale_jobs(_merge_jobs(snapshot.get("jobs") or [], scored))
        partial_at = _utc_now()
        updated = {
            **snapshot,
            "jobs": merged,
            "partialScrapedAt": partial_at,
            "lastHours": clamp_scrape_hours(hours),
            "lastRoles": roles,
        }
        _persist_snapshot(db, updated)
        _scrape_status["indexedJobs"] = len(merged)
        _scrape_status["lastResult"] = f"Indexed {len(merged)} roles so far"


def get_status() -> dict[str, Any]:
    return dict(_scrape_status)


def get_snapshot(db: Session) -> dict[str, Any]:
    snapshot = _load_snapshot(db)
    jobs = snapshot.get("jobs") or []
    return {
        "scrapedAt": snapshot.get("scrapedAt") or snapshot.get("partialScrapedAt"),
        "totalJobs": len(jobs),
        "companies": len({job.get("companyName") for job in jobs if job.get("companyName")}),
        "jobs": jobs,
    }


def rescore_all(db: Session) -> dict[str, Any]:
    snapshot = _load_snapshot(db)
    profile = get_kv(db, "profile") or {}
    jobs = _score_jobs(snapshot.get("jobs") or [], profile)
    snapshot["jobs"] = jobs
    snapshot["rescoredAt"] = _utc_now()
    _persist_snapshot(db, snapshot)
    return {"success": True, "rescored": len(jobs), "rescoredAt": snapshot["rescoredAt"]}


def filter_jobs(
    jobs: list[dict[str, Any]],
    *,
    q: str = "",
    company: str = "",
    location: str = "",
    role: str = "",
    freshness: FreshnessOption = "all",
    sponsorship: str = "all",
    sort: SortOption = "relevancy",
    page: int = 1,
    per_page: int = 30,
) -> tuple[list[dict[str, Any]], int]:
    filtered = list(jobs)

    if q:
        needle = q.lower()
        filtered = [
            job
            for job in filtered
            if needle in job.get("title", "").lower()
            or needle in job.get("companyName", "").lower()
            or needle in job.get("description", "").lower()
        ]

    if company:
        needle = company.lower()
        filtered = [job for job in filtered if needle in job.get("companyName", "").lower()]

    if location:
        needle = location.lower()
        filtered = [job for job in filtered if needle in job.get("location", "").lower()]

    if role:
        role_keys = [part.strip() for part in role.split(",") if part.strip()]
        compiled = scraper_service.compile_role_patterns(role_keys or None)

        def matches(job: dict[str, Any]) -> bool:
            return scraper_service.matches_title(job.get("title", ""), compiled)

        filtered = [job for job in filtered if matches(job)]

    if freshness != "all":
        hours = int(freshness)
        filtered = [
            job
            for job in filtered
            if relevancy_engine.compute_freshness(job.get("updatedAt", "")).get("hours_ago", 999) <= hours
        ]

    if sponsorship and sponsorship != "all":
        if sponsorship == "likely":
            filtered = [job for job in filtered if job.get("h1bStatus") == "likely"]
        elif sponsorship == "unlikely":
            filtered = [job for job in filtered if job.get("h1bStatus") == "unlikely"]
        elif sponsorship in {"friendly", "needs-friendly"}:
            filtered = [
                job
                for job in filtered
                if job.get("h1bStatus") in {"likely", "unknown", None, ""}
            ]

    if sort == "company":
        filtered.sort(key=lambda job: (job.get("companyName", "").lower(), -(job.get("relevancyScore") or 0)))
    elif sort == "date":
        filtered.sort(key=lambda job: job.get("updatedAt") or "", reverse=True)
    else:
        filtered.sort(key=lambda job: job.get("relevancyScore") or 0, reverse=True)

    total = len(filtered)
    start = max(page - 1, 0) * per_page
    end = start + per_page
    page_jobs = filtered[start:end]

    enriched: list[dict[str, Any]] = []
    for job in page_jobs:
        freshness_meta = relevancy_engine.compute_freshness(job.get("updatedAt", ""))
        with_h1b = job if job.get("h1bStatus") else apply_h1b_fields(job)
        enriched.append({**with_h1b, "freshness": freshness_meta})

    return enriched, total


def get_job_by_url(db: Session, url: str) -> dict[str, Any] | None:
    """Find scraped job by apply URL (normalized)."""
    if not url.strip():
        return None
    normalized = url.strip().split("?")[0].rstrip("/")
    snapshot = _load_snapshot(db)
    for job in snapshot.get("jobs") or []:
        job_url = str(job.get("url") or "").split("?")[0].rstrip("/")
        if job_url and job_url == normalized:
            return apply_h1b_fields(job) if not job.get("h1bStatus") else job
    return None


def get_job_by_id(db: Session, job_id: str) -> dict[str, Any] | None:
    snapshot = _load_snapshot(db)
    for job in snapshot.get("jobs") or []:
        if job.get("id") == job_id:
            return job
    return None


def get_stats(db: Session) -> dict[str, Any]:
    snapshot = _load_snapshot(db)
    jobs = snapshot.get("jobs") or []
    strong = sum(1 for job in jobs if (job.get("relevancyScore") or 0) >= 75)
    moderate = sum(1 for job in jobs if 50 <= (job.get("relevancyScore") or 0) < 75)
    fresh = sum(
        1
        for job in jobs
        if relevancy_engine.compute_freshness(job.get("updatedAt", "")).get("hours_ago", 999) <= 48
    )
    companies = {job.get("companyName") for job in jobs if job.get("companyName")}
    return {
        "totalJobs": len(jobs),
        "indexedCompanies": len(companies),
        "strongMatch": strong,
        "moderateMatch": moderate,
        "fresh48h": fresh,
        "scrapedAt": snapshot.get("scrapedAt") or snapshot.get("partialScrapedAt"),
    }


def save_job_to_tracker(db: Session, job_id: str) -> dict[str, Any]:
    job = get_job_by_id(db, job_id)
    if not job:
        return {"success": False, "error": "Job not found"}
    application = upsert_entity(
        db,
        "application",
        {
            "companyName": job.get("companyName") or "Unknown",
            "roleTitle": job.get("title") or "Unknown role",
            "location": job.get("location") or "",
            "url": job.get("url") or "",
            "status": "saved",
            "source": "job_discover",
            "notes": (
                f"Saved from Job discover (score {job.get('relevancyScore', 0)}%)"
                + (f"\nSalary: {job.get('salaryRange')}" if job.get("salaryRange") else "")
                + (f"\nH1B: {job.get('h1bLabel')}" if job.get("h1bLabel") else "")
            ),
        },
    )
    return {"success": True, "application": application, "job": job}


def _profile_for_outreach(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "first_name": profile.get("firstName") or profile.get("first_name") or "",
        "last_name": profile.get("lastName") or profile.get("last_name") or "",
        "current_title": profile.get("currentTitle") or profile.get("current_title") or "",
        "current_company": profile.get("currentCompany") or profile.get("current_company") or "",
        "skills": profile.get("skills") or "",
        "years_experience": profile.get("yearsExperience") or profile.get("years_experience") or 0,
    }


def job_outreach(db: Session, job_id: str, contact_name: str = "[Name]") -> dict[str, Any]:
    job = get_job_by_id(db, job_id)
    if not job:
        return {"success": False, "error": "Job not found"}
    profile = get_kv(db, "profile") or {}
    outreach_profile = _profile_for_outreach(profile)
    il_job = {
        "title": job.get("title", ""),
        "company": job.get("companyName", ""),
        "department": job.get("department", ""),
    }
    message = relevancy_engine.generate_outreach_message(outreach_profile, il_job, contact_name)
    urls = relevancy_engine.get_recruiter_urls(
        job.get("companyName", ""),
        job.get("title", ""),
        job.get("department", ""),
    )
    return {"success": True, "message": message, "job": job, **urls}


def job_recruiter_urls(db: Session, job_id: str) -> dict[str, Any]:
    job = get_job_by_id(db, job_id)
    if not job:
        return {"success": False, "error": "Job not found"}
    urls = relevancy_engine.get_recruiter_urls(
        job.get("companyName", ""),
        job.get("title", ""),
        job.get("department", ""),
    )
    return {"success": True, "job": job, **urls}


async def run_scrape(
    db: Session,
    *,
    hours: int = 168,
    roles: str = "",
    mode: ScrapeMode = "ats",
) -> dict[str, Any]:
    async with _scrape_lock:
        existing = _load_snapshot(db)
        _scrape_status.update(
            running=True,
            progress="Starting...",
            lastResult="",
            indexedJobs=len(existing.get("jobs") or []),
        )
        try:
            hours = clamp_scrape_hours(hours)
            role_keys = [part.strip() for part in roles.split(",") if part.strip()] or None
            profile = get_kv(db, "profile") or {}
            raw_jobs: list[dict[str, Any]] = []

            def on_progress(done: int, total: int, label: str = "companies") -> None:
                _scrape_status["progress"] = f"{done}/{total} {label}"

            async def on_batch(raw_batch: list[dict[str, Any]]) -> None:
                await _append_scraped_batch(db, raw_batch, profile, hours=hours, roles=roles)

            if mode in {"ats", "all"}:
                _scrape_status["progress"] = "ATS scrape starting..."
                ats_jobs = await scraper_service.scrape_jobs(
                    role_keys=role_keys,
                    hours=hours,
                    progress_callback=lambda done, total: on_progress(done, total, "ATS companies"),
                    on_batch=on_batch,
                )
                raw_jobs.extend(ats_jobs)

            if mode in {"bigtech", "all"}:
                _scrape_status["progress"] = "Big Tech scrape starting..."
                search_terms = None
                if role_keys:
                    role_map = {
                        "pm": "Product Manager",
                        "swe": "Software Engineer",
                        "ux": "UX Designer",
                        "tpm": "Program Manager",
                        "product": "Product",
                        "presales": "Solutions Engineer",
                    }
                    search_terms = [role_map[k] for k in role_keys if k in role_map] or None
                bigtech_jobs = await bigtech_scrapers.scrape_bigtech(
                    search_terms=search_terms,
                    progress_callback=lambda done, total: on_progress(done, total, "Big Tech"),
                )
                if bigtech_jobs:
                    await _append_scraped_batch(db, bigtech_jobs, profile, hours=hours, roles=roles)
                raw_jobs.extend(bigtech_jobs)

            if mode in {"apify", "all"}:
                _scrape_status["progress"] = "Apify scrape starting..."
                apify_config = apify_service.load_apify_config()
                if not apify_config.get("token"):
                    if mode == "apify":
                        raise RuntimeError(
                            "Apify token not configured. Set APIFY_TOKEN in apps/api/.env or data/job_discover/apify_config.yaml"
                        )
                else:
                    search_terms = None
                    if role_keys:
                        role_map = {
                            "pm": "Product Manager",
                            "swe": "Software Engineer",
                            "ux": "UX Designer",
                            "tpm": "Program Manager",
                        }
                        search_terms = [role_map[k] for k in role_keys if k in role_map]
                    apify_jobs = await apify_service.scrape_via_apify(
                        platform="linkedin",
                        search_terms=search_terms,
                        max_results=100,
                    )
                    if apify_jobs:
                        await _append_scraped_batch(db, apify_jobs, profile, hours=hours, roles=roles)
                    raw_jobs.extend(apify_jobs)

            snapshot = _load_snapshot(db)
            scraped_at = _utc_now()
            snapshot["scrapedAt"] = scraped_at
            snapshot.pop("partialScrapedAt", None)
            snapshot["lastHours"] = hours
            snapshot["lastRoles"] = roles
            snapshot["lastScrapeMode"] = mode
            snapshot["jobs"] = _prune_stale_jobs(snapshot.get("jobs") or [])
            _persist_snapshot(db, snapshot)

            total_jobs = len(snapshot.get("jobs") or [])
            mode_label = {"ats": "ATS", "bigtech": "Big Tech", "apify": "Apify", "all": "Full"}[mode]
            result = {
                "success": True,
                "scraped": len(raw_jobs),
                "totalJobs": total_jobs,
                "scrapedAt": scraped_at,
                "mode": mode,
            }
            _scrape_status.update(
                running=False,
                progress="Complete",
                lastResult=f"{mode_label}: fetched {len(raw_jobs)} roles ({total_jobs} total indexed)",
                lastScrapedAt=scraped_at,
                indexedJobs=total_jobs,
            )
            return result
        except Exception as exc:
            message = str(exc)
            _scrape_status.update(running=False, progress="Failed", lastResult=message)
            return {"success": False, "error": message}


async def start_scrape_background(
    *,
    hours: int = 168,
    roles: str = "",
    mode: ScrapeMode = "ats",
) -> dict[str, Any]:
    if _scrape_status["running"]:
        return {"success": False, "error": "Scrape already running"}

    async def _runner() -> None:
        with session_scope() as db:
            await run_scrape(db, hours=hours, roles=roles, mode=mode)

    asyncio.create_task(_runner())
    return {"success": True, "status": "started", "mode": mode}
