"""Job discovery storage, scraping orchestration, and relevancy scoring."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.db.store import get_kv, session_scope, set_kv, upsert_entity
from app.services.application_assistant.candidate_match_context import (
    accomplishment_text,
    extract_resume_text,
    normalize_profile_skills,
    work_experience_text,
)
from app.services.job_discover import apify_service, bigtech_scrapers, relevancy_engine, scraper_service
from app.services.job_discover.h1b_sponsorship import apply_h1b_fields

KV_KEY = "job_discover"
DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "job_discover"
SNAPSHOT_FILE = DATA_DIR / "jobs_snapshot.json"

SortOption = Literal["relevancy", "date", "company"]
PostedAgoOption = Literal["12", "24", "48", "72", "168", "336", "720", "all"]
FreshnessOption = PostedAgoOption
POSTED_AGO_HOURS = frozenset({12, 24, 48, 72, 168, 336, 720})
ScrapeMode = Literal["ats", "bigtech", "apify", "all"]

# Hard cap: never scrape or retain jobs older than 30 days.
MAX_SCRAPE_HOURS = 720

_scrape_lock = asyncio.Lock()
_save_lock = asyncio.Lock()
_scrape_task: asyncio.Task[None] | None = None
SCRAPE_STALE_SECONDS = 20 * 60
_scrape_status: dict[str, Any] = {
    "running": False,
    "progress": "",
    "lastResult": "",
    "lastScrapedAt": None,
    "startedAt": None,
    "lastProgressAt": None,
    "indexedJobs": 0,
    "strongMatches": 0,
    "moderateMatches": 0,
    "freshMatches": 0,
    "indexedCompanies": 0,
}


def _snapshot_stats(jobs: list[dict[str, Any]]) -> dict[str, int]:
    strong = moderate = fresh = 0
    for job in jobs:
        score = job.get("relevancyScore") or 0
        if score >= 75:
            strong += 1
        elif score >= 50:
            moderate += 1
        if relevancy_engine.compute_freshness(job.get("updatedAt", "")).get("hours_ago", 999) <= 48:
            fresh += 1
    companies = len({job.get("companyName") for job in jobs if job.get("companyName")})
    return {
        "indexedJobs": len(jobs),
        "strongMatches": strong,
        "moderateMatches": moderate,
        "freshMatches": fresh,
        "indexedCompanies": companies,
    }


def _apply_snapshot_stats(jobs: list[dict[str, Any]]) -> None:
    _scrape_status.update(_snapshot_stats(jobs))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def compute_match_profile_hash(
    profile: dict[str, Any],
    *,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
) -> str:
    """Fingerprint profile + resume + accomplishments for score invalidation."""
    parts = [
        json.dumps(profile, sort_keys=True, default=str)[:8000],
        extract_resume_text(documents or {})[:4000],
        accomplishment_text(accomplishments or [])[:2000],
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _merge_jobs_into_snapshot(db: Session, updated_jobs: list[dict[str, Any]]) -> None:
    if not updated_jobs:
        return
    snapshot = _load_snapshot(db)
    by_id = {job["id"]: job for job in (snapshot.get("jobs") or []) if job.get("id")}
    for job in updated_jobs:
        if job.get("id"):
            by_id[job["id"]] = job
    snapshot["jobs"] = list(by_id.values())
    _persist_snapshot(db, snapshot)


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


def _normalize_skills(skills: Any) -> str:
    if isinstance(skills, list):
        return ", ".join(str(item).strip() for item in skills if str(item).strip())
    if skills is None:
        return ""
    return str(skills)


def _profile_for_scoring(
    profile: dict[str, Any] | None,
    *,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not profile:
        return {}
    skill_terms = normalize_profile_skills(profile)
    resume_text = extract_resume_text(documents)
    experience_text = work_experience_text(profile)
    accomplishment_blob = accomplishment_text(accomplishments)
    return {
        "current_title": profile.get("currentTitle") or profile.get("current_title") or profile.get("headline") or "",
        "skills": ", ".join(skill_terms) if skill_terms else _normalize_skills(profile.get("skills")),
        "years_experience": profile.get("yearsExperience") or profile.get("years_experience") or 0,
        "city": profile.get("city") or "",
        "state": profile.get("state") or profile.get("region") or "",
        "resume_text": resume_text,
        "work_experience_text": experience_text,
        "accomplishment_text": accomplishment_blob,
    }


def _score_jobs(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any] | None,
    *,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    scoring_profile = _profile_for_scoring(profile, documents=documents, accomplishments=accomplishments)
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


def _attach_heuristic_gaps(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any] | None,
    *,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
    lightweight: bool = True,
) -> list[dict[str, Any]]:
    from app.services.application_assistant.candidate_match_context import match_sources_used
    from app.services.job_discover.gap_analysis import attach_gap_to_job

    effective_profile = profile or {}
    analyzed_at = _utc_now()
    sources = match_sources_used(effective_profile, documents=documents, accomplishments=accomplishments)
    updated: list[dict[str, Any]] = []
    for job in jobs:
        result_score = job.get("relevancyScore") or 0
        heuristic_match = {
            "overallScore": result_score,
            "strongMatches": job.get("keywordsMatched") or [],
            "missingQualifications": [],
            "potentialConcerns": [],
            "explanation": "",
            "matchMethod": "heuristic",
            "matchSources": sources,
        }
        updated.append(
            attach_gap_to_job(
                job,
                heuristic_match,
                effective_profile,
                documents=documents,
                accomplishments=accomplishments,
                analyzed_at=analyzed_at,
                lightweight=lightweight,
            )
        )
    return updated


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
    db.commit()


def _load_snapshot(db: Session) -> dict[str, Any]:
    kv_snapshot = get_kv(db, KV_KEY) if get_kv(db, KV_KEY) is not None else {}
    file_snapshot = _read_snapshot_file() or {}
    kv_jobs = kv_snapshot.get("jobs") or []
    file_jobs = file_snapshot.get("jobs") or []
    if len(file_jobs) > len(kv_jobs):
        snapshot = file_snapshot
    elif kv_jobs:
        snapshot = kv_snapshot
    elif file_jobs:
        snapshot = file_snapshot
    else:
        return kv_snapshot or {"jobs": []}

    jobs = _prune_stale_jobs(snapshot.get("jobs") or [])
    if len(jobs) != len(snapshot.get("jobs") or []):
        snapshot = {**snapshot, "jobs": jobs}
        _persist_snapshot(db, snapshot)
    elif len(file_jobs) > len(kv_jobs):
        _persist_snapshot(db, snapshot)
    elif not SNAPSHOT_FILE.exists() and jobs:
        _write_snapshot_file(snapshot)
    return snapshot


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
        from app.db.store import list_entities

        documents = get_kv(db, "documents") or {}
        accomplishments = list_entities(db, "accomplishment")
        scored = _score_jobs(
            normalized,
            profile,
            documents=documents,
            accomplishments=accomplishments,
        )
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
        merged_jobs = updated.get("jobs") or []
        _apply_snapshot_stats(merged_jobs)
        _scrape_status["lastResult"] = f"Indexed {len(merged_jobs)} roles so far"


def _touch_scrape_progress(message: str | None = None) -> None:
    _scrape_status["lastProgressAt"] = _utc_now()
    if message:
        _scrape_status["progress"] = message


def _maybe_clear_stale_scrape() -> bool:
    if not _scrape_status.get("running"):
        return False
    last = _scrape_status.get("lastProgressAt") or _scrape_status.get("startedAt")
    if not last:
        return False
    try:
        dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        age = (datetime.now(UTC) - dt).total_seconds()
        if age >= SCRAPE_STALE_SECONDS:
            cancel_scrape(reason="Scrape timed out (no progress for 20+ minutes). Partial results were kept.")
            return True
    except (ValueError, TypeError):
        pass
    return False


def cancel_scrape(*, reason: str = "Scrape cancelled — partial results kept.") -> dict[str, Any]:
    global _scrape_task
    if _scrape_task and not _scrape_task.done():
        _scrape_task.cancel()
    _scrape_status.update(running=False, progress="Cancelled", lastResult=reason)
    return {"success": True, "cancelled": True, "message": reason}


def get_status() -> dict[str, Any]:
    _maybe_clear_stale_scrape()
    return {
        **dict(_scrape_status),
        "tier1Rescore": get_tier1_rescore_status(),
        "postRescore": get_post_rescore_status(),
    }


def get_snapshot(db: Session) -> dict[str, Any]:
    snapshot = _load_snapshot(db)
    jobs = snapshot.get("jobs") or []
    return {
        "scrapedAt": snapshot.get("scrapedAt") or snapshot.get("partialScrapedAt"),
        "totalJobs": len(jobs),
        "companies": len({job.get("companyName") for job in jobs if job.get("companyName")}),
        "jobs": jobs,
    }


async def start_tier1_rescore_background(*, force: bool = False) -> dict[str, Any]:
    """Tier 1: heuristic relevancy for all indexed jobs (background, no LLM)."""
    global _tier1_rescore_task

    if _tier1_rescore_task and not _tier1_rescore_task.done():
        return {"started": False, "error": "Tier 1 rescore already running"}

    async def _run() -> None:
        global _tier1_rescore_status
        from app.db.store import list_entities

        _tier1_rescore_status.update(
            running=True,
            progress="Starting match score refresh…",
            lastResult="",
            processed=0,
            total=0,
        )
        try:

            def _work() -> dict[str, Any]:
                with session_scope() as db:
                    snapshot = _load_snapshot(db)
                    profile = get_kv(db, "profile") or {}
                    documents = get_kv(db, "documents") or {}
                    accomplishments = list_entities(db, "accomplishment")
                    profile_hash = compute_match_profile_hash(
                        profile,
                        documents=documents,
                        accomplishments=accomplishments,
                    )
                    if not force and snapshot.get("profileHash") == profile_hash:
                        return {"skipped": True, "reason": "Profile unchanged", "rescored": 0}

                    jobs = list(snapshot.get("jobs") or [])
                    _tier1_rescore_status["total"] = len(jobs)
                    scored = _score_jobs(
                        jobs,
                        profile,
                        documents=documents,
                        accomplishments=accomplishments,
                    )
                    snapshot["jobs"] = scored
                    snapshot["profileHash"] = profile_hash
                    snapshot["rescoredAt"] = _utc_now()
                    snapshot["rescoreMethod"] = "tier1_heuristic"
                    _persist_snapshot(db, snapshot)
                    return {"skipped": False, "rescored": len(scored)}

            result = await asyncio.to_thread(_work)
            if result.get("skipped"):
                _tier1_rescore_status.update(
                    running=False,
                    progress="Skipped",
                    lastResult=str(result.get("reason") or "Profile unchanged"),
                )
            else:
                count = int(result.get("rescored") or 0)
                _tier1_rescore_status.update(
                    running=False,
                    progress="Complete",
                    processed=count,
                    lastResult=f"Updated match scores for {count:,} jobs",
                )
        except Exception as exc:
            _tier1_rescore_status.update(
                running=False,
                progress="Failed",
                lastResult=str(exc)[:200],
            )

    _tier1_rescore_task = asyncio.create_task(_run())
    return {"started": True}


async def analyze_jobs_async(db: Session, job_ids: list[str], *, use_qwen: bool = True) -> dict[str, Any]:
    """Tier 2/3: gap analysis (+ optional Qwen) for specific jobs only."""
    from app.db.store import list_entities

    unique_ids = [job_id for job_id in dict.fromkeys(job_ids) if job_id]
    if not unique_ids:
        return {"success": False, "error": "No jobs to analyze", "analyzed": 0}

    def _work() -> list[dict[str, Any]]:
        with session_scope() as thread_db:
            snapshot = _load_snapshot(thread_db)
            profile = get_kv(thread_db, "profile") or {}
            documents = get_kv(thread_db, "documents") or {}
            accomplishments = list_entities(thread_db, "accomplishment")
            profile_hash = compute_match_profile_hash(
                profile,
                documents=documents,
                accomplishments=accomplishments,
            )
            by_id = {job["id"]: job for job in (snapshot.get("jobs") or []) if job.get("id")}
            subset = [by_id[job_id] for job_id in unique_ids if job_id in by_id]
            if not subset:
                return []

            scored = _score_jobs(
                subset,
                profile,
                documents=documents,
                accomplishments=accomplishments,
            )
            scored = _attach_heuristic_gaps(
                scored,
                profile,
                documents=documents,
                accomplishments=accomplishments,
                lightweight=False,
            )
            for job in scored:
                job["gapProfileHash"] = profile_hash
                by_id[job["id"]] = job
            snapshot["jobs"] = list(by_id.values())
            _persist_snapshot(thread_db, snapshot)
            return scored

    analyzed = await asyncio.to_thread(_work)
    if not analyzed:
        return {"success": False, "error": "Jobs not found", "analyzed": 0}

    qwen_started = False
    if use_qwen:
        qwen_result = await start_qwen_rescore_background(job_ids=[job["id"] for job in analyzed if job.get("id")])
        qwen_started = bool(qwen_result.get("started"))

    return {
        "success": True,
        "analyzed": len(analyzed),
        "jobs": analyzed,
        "qwenStarted": qwen_started,
    }


async def rescore_jobs_async(db: Session, job_ids: list[str], *, use_qwen: bool = True) -> dict[str, Any]:
    """Analyze specific jobs (gap + optional Qwen). Used for gap click / add to assistant."""
    result = await analyze_jobs_async(db, job_ids, use_qwen=use_qwen)
    return {
        "success": result.get("success", False),
        "rescored": result.get("analyzed", 0),
        "error": result.get("error"),
        "postRescore": {"started": result.get("qwenStarted", False)} if result.get("qwenStarted") else None,
    }


_tier1_rescore_task: asyncio.Task[None] | None = None
_tier1_rescore_status: dict[str, Any] = {
    "running": False,
    "progress": "",
    "lastResult": "",
    "processed": 0,
    "total": 0,
}


def get_tier1_rescore_status() -> dict[str, Any]:
    return dict(_tier1_rescore_status)


async def rescore_all_async(db: Session, *, use_qwen: bool = False, qwen_limit: int = 50) -> dict[str, Any]:
    """Start Tier 1 background rescore for all jobs."""
    return await start_tier1_rescore_background(force=use_qwen)


_post_rescore_task: asyncio.Task[None] | None = None
_post_rescore_status: dict[str, Any] = {
    "running": False,
    "phase": "",
    "progress": "",
    "lastResult": "",
    "processed": 0,
    "total": 0,
}


def get_post_rescore_status() -> dict[str, Any]:
    return {
        **dict(_post_rescore_status),
        "qwenRescore": get_rescore_qwen_status(),
    }


async def start_post_rescore_background(*, use_qwen: bool = True, job_ids: list[str] | None = None) -> dict[str, Any]:
    """Run Qwen gap refinement for a specific set of jobs (visible page)."""
    global _post_rescore_task

    if _post_rescore_task and not _post_rescore_task.done():
        return {"started": False, "error": "Post-rescore analysis already running"}

    target_ids = [job_id for job_id in dict.fromkeys(job_ids or []) if job_id]
    if not target_ids:
        return {"started": False, "error": "No jobs selected for analysis"}

    async def _run() -> None:
        global _post_rescore_status
        _post_rescore_status.update(
            running=True,
            phase="qwen" if use_qwen else "done",
            progress="Starting analysis…",
            lastResult="",
            processed=0,
            total=len(target_ids),
        )
        try:
            if use_qwen:
                _post_rescore_status.update(progress=f"Qwen analyzing {len(target_ids)} visible jobs…")
                qwen_result = await start_qwen_rescore_background(job_ids=target_ids)
                if qwen_result.get("started") and _rescore_qwen_task is not None:
                    await _rescore_qwen_task
                    _post_rescore_status.update(
                        phase="done",
                        progress="Complete",
                        processed=len(target_ids),
                        lastResult=get_rescore_qwen_status().get("lastResult", ""),
                    )
                elif qwen_result.get("error"):
                    _post_rescore_status.update(lastResult=qwen_result["error"])
            else:
                _post_rescore_status.update(
                    phase="done",
                    progress="Complete",
                    processed=len(target_ids),
                    lastResult=f"Gap analysis stored for {len(target_ids)} jobs",
                )
        except Exception as exc:
            _post_rescore_status.update(
                progress="Failed",
                lastResult=str(exc)[:200],
            )
        finally:
            _post_rescore_status["running"] = False

    _post_rescore_task = asyncio.create_task(_run())
    return {"started": True, "jobCount": len(target_ids)}


_rescore_qwen_task: asyncio.Task[None] | None = None
_rescore_qwen_status: dict[str, Any] = {
    "running": False,
    "progress": "",
    "lastResult": "",
    "scored": 0,
    "total": 0,
}


def get_rescore_qwen_status() -> dict[str, Any]:
    return dict(_rescore_qwen_status)


async def start_qwen_rescore_background(*, limit: int = 50, job_ids: list[str] | None = None) -> dict[str, Any]:
    """Score selected jobs with Qwen in the background."""
    global _rescore_qwen_task

    if _rescore_qwen_task and not _rescore_qwen_task.done():
        return {"started": False, "error": "Qwen rescore already running"}

    target_ids = [job_id for job_id in dict.fromkeys(job_ids or []) if job_id]
    limit = max(1, min(limit, 200))

    async def _run() -> None:
        global _rescore_qwen_status
        _rescore_qwen_status.update(
            running=True,
            progress="Starting Qwen rescore…",
            lastResult="",
            scored=0,
            total=len(target_ids) if target_ids else limit,
        )
        try:
            with session_scope() as db:
                from app.db.store import list_entities
                from app.services.application_assistant.qwen_job_match import score_jobs_batch_with_qwen

                snapshot = _load_snapshot(db)
                profile = get_kv(db, "profile") or {}
                documents = get_kv(db, "documents") or {}
                accomplishments = list_entities(db, "accomplishment")
                all_jobs = list(snapshot.get("jobs") or [])
                by_id = {job["id"]: job for job in all_jobs if job.get("id")}
                if target_ids:
                    selected_jobs = [by_id[job_id] for job_id in target_ids if job_id in by_id]
                else:
                    selected_jobs = sorted(
                        all_jobs,
                        key=lambda j: j.get("relevancyScore") or 0,
                        reverse=True,
                    )[:limit]
                _rescore_qwen_status["total"] = len(selected_jobs)
                _rescore_qwen_status["progress"] = f"Qwen scoring {len(selected_jobs)} jobs…"

                scored_jobs = await score_jobs_batch_with_qwen(
                    db,
                    selected_jobs,
                    profile=profile,
                    documents=documents,
                    accomplishments=accomplishments,
                    concurrency=2,
                )
                scored_by_id = {job["id"]: job for job in scored_jobs if job.get("id")}
                merged = [scored_by_id.get(job["id"], job) if job.get("id") in scored_by_id else job for job in all_jobs]
                snapshot["jobs"] = merged
                snapshot["qwenRescoredAt"] = _utc_now()
                snapshot["rescoreMethod"] = "qwen_page"
                _persist_snapshot(db, snapshot)
                qwen_count = sum(1 for job in scored_jobs if job.get("matchMethod") == "qwen")
                _rescore_qwen_status.update(
                    running=False,
                    progress="Complete",
                    lastResult=f"Qwen scored {qwen_count} of {len(selected_jobs)} jobs",
                    scored=qwen_count,
                )
        except Exception as exc:
            _rescore_qwen_status.update(
                running=False,
                progress="Failed",
                lastResult=str(exc)[:200],
            )

    _rescore_qwen_task = asyncio.create_task(_run())
    return {"started": True, "limit": len(target_ids) if target_ids else limit}


def rescore_all(db: Session) -> dict[str, Any]:
    return {"success": False, "error": "Use rescore_jobs_async with jobIds", "rescored": 0}


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
        try:
            hours = int(freshness)
        except (TypeError, ValueError):
            hours = -1
        if hours in POSTED_AGO_HOURS:
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


def get_location_options(jobs: list[dict[str, Any]], *, limit: int = 80) -> list[dict[str, Any]]:
    """Distinct location labels from indexed jobs, sorted by frequency."""
    counts: Counter[str] = Counter()
    for job in jobs:
        loc = (job.get("location") or "").strip()
        if not loc:
            counts["Unspecified"] += 1
            continue
        parts = [p.strip() for p in loc.replace(";", "|").split("|") if p.strip()]
        seen_in_job: set[str] = set()
        for part in parts or [loc]:
            key = part[:120]
            if key in seen_in_job:
                continue
            counts[key] += 1
            seen_in_job.add(key)
    return [{"value": label, "label": label, "count": count} for label, count in counts.most_common(limit)]


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
        existing_jobs = existing.get("jobs") or []
        _scrape_status.update(
            running=True,
            progress="Starting...",
            lastResult="",
            startedAt=_utc_now(),
            lastProgressAt=_utc_now(),
            **_snapshot_stats(existing_jobs),
        )
        try:
            hours = clamp_scrape_hours(hours)
            role_keys = [part.strip() for part in roles.split(",") if part.strip()] or None
            profile = get_kv(db, "profile") or {}
            raw_jobs: list[dict[str, Any]] = []

            def on_progress(done: int, total: int, label: str = "companies") -> None:
                _touch_scrape_progress(f"{done}/{total} {label}")

            async def on_batch(raw_batch: list[dict[str, Any]]) -> None:
                await _append_scraped_batch(db, raw_batch, profile, hours=hours, roles=roles)

            if mode in {"ats", "all"}:
                _touch_scrape_progress("ATS scrape starting...")
                try:
                    ats_jobs = await asyncio.wait_for(
                        scraper_service.scrape_jobs(
                            role_keys=role_keys,
                            hours=hours,
                            progress_callback=lambda done, total: on_progress(done, total, "ATS boards"),
                            on_batch=on_batch,
                        ),
                        timeout=45 * 60,
                    )
                except TimeoutError:
                    snapshot = _load_snapshot(db)
                    ats_jobs = []
                    _scrape_status["lastResult"] = (
                        f"ATS scrape timed out after 45 minutes — kept {len(snapshot.get('jobs') or [])} indexed roles"
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
                **_snapshot_stats(snapshot.get("jobs") or []),
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
    global _scrape_task
    _maybe_clear_stale_scrape()
    if _scrape_status["running"]:
        return {"success": False, "error": "Scrape already running"}

    async def _runner() -> None:
        try:
            with session_scope() as db:
                await run_scrape(db, hours=hours, roles=roles, mode=mode)
        except asyncio.CancelledError:
            _scrape_status.update(
                running=False,
                progress="Cancelled",
                lastResult="Scrape cancelled — partial results kept.",
            )
            raise
        except Exception as exc:
            _scrape_status.update(running=False, progress="Failed", lastResult=str(exc))

    _scrape_task = asyncio.create_task(_runner())
    return {"success": True, "status": "started", "mode": mode}
