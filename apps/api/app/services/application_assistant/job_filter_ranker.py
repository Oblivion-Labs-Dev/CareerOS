"""Deterministic hard filter & AI ranking engine for Autopilot jobs."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.services.application_assistant.domain import AutopilotJobStatus
from app.services.application_assistant.persistence import list_autopilot_jobs
from app.services.application_assistant.qwen_job_match import evaluate_job_match


DEFAULT_MIN_MATCH_SCORE = 75.0
DEFAULT_MAX_POST_AGE_DAYS = 7
DEFAULT_MAX_APPLICATIONS_PER_RUN = 25


def normalize_title(title: str) -> str:
    cleaned = re.sub(r"[^\w\s]", "", title.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_company(company: str) -> str:
    cleaned = re.sub(r"(inc|llc|corp|corporation|ltd|co)\b", "", company.lower(), flags=re.I)
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def generate_composite_job_key(company: str, title: str, app_url: str = "", external_id: str = "") -> str:
    norm_c = normalize_company(company)
    norm_t = normalize_title(title)
    if external_id:
        return f"{norm_c}::{norm_t}::{external_id.lower().strip()}"
    if app_url:
        from urllib.parse import urlparse
        parsed = urlparse(app_url)
        clean_url = f"{parsed.netloc}{parsed.path}".rstrip("/")
        return f"{norm_c}::{norm_t}::{clean_url}"
    return f"{norm_c}::{norm_t}"


def evaluate_hard_filters(
    job: dict[str, Any],
    profile: dict[str, Any],
    existing_jobs: list[dict[str, Any]],
    settings: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Perform deterministic pre-checks before executing AI match scoring.

    Returns (passed, skip_reason).
    """
    opts = settings or {}
    max_age_days = opts.get("maxPostAgeDays", DEFAULT_MAX_POST_AGE_DAYS)

    company = job.get("company") or ""
    title = job.get("title") or ""
    app_url = job.get("applicationUrl") or job.get("listingUrl") or ""
    external_id = job.get("externalJobId") or ""

    if not company or not title:
        return False, "Missing company or job title"

    # 1. Duplicate Application Protection
    if not opts.get("allowDuplicates", False):
        job_key = generate_composite_job_key(company, title, app_url, external_id)
        for existing in existing_jobs:
            ex_key = generate_composite_job_key(
                existing.get("company") or "",
                existing.get("title") or "",
                existing.get("applicationUrl") or "",
                existing.get("externalJobId") or "",
            )
            ex_status = existing.get("status")
            if job_key == ex_key and ex_status in (
                AutopilotJobStatus.SUBMITTED.value,
                AutopilotJobStatus.APPLYING.value,
                AutopilotJobStatus.STAGED.value,
                AutopilotJobStatus.QUEUED.value,
            ):
                return False, f"Duplicate application already in state: {ex_status}"

    # 2. Posting Recency Check
    date_posted_str = job.get("datePosted")
    if date_posted_str:
        try:
            posted_date = datetime.fromisoformat(date_posted_str.replace("Z", "+00:00"))
            if posted_date.tzinfo is None:
                posted_date = posted_date.replace(tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
            if posted_date < cutoff:
                return False, f"Posting age exceeds limit ({max_age_days} days)"
        except Exception:
            pass

    # 3. Employment Type & Location Constraints
    job_emp = (job.get("employmentType") or "").lower()
    pref_emp = (profile.get("preferredEmploymentType") or "").lower()
    if pref_emp and job_emp and pref_emp not in job_emp and "full" in pref_emp and "part" in job_emp:
        return False, f"Employment type mismatch: job is {job_emp}, preferred is {pref_emp}"

    job_loc = (job.get("location") or "").lower()
    job_wp = (job.get("workplaceType") or "").lower()
    profile_loc = (profile.get("location") or "").lower()
    remote_pref = profile.get("remoteOnly", False)

    if remote_pref and "remote" not in job_wp and "remote" not in job_loc:
        return False, "Job is not Remote, candidate requires Remote Only"

    return True, ""


def filter_and_rank_jobs(
    db: Session | list[dict[str, Any]],
    raw_jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Process a list of discovered jobs:

    1. Run hard filters (deterministic)
    2. Run Qwen/Ollama match scoring
    3. Filter by min match score threshold (with fallback so batch queue never starves)
    4. Sort by match score & date posted
    """
    opts = settings or {}
    min_score = float(opts.get("minMatchScore") or 0.0)
    max_apps = int(opts.get("maxApplicationsPerRun") or opts.get("targetProcessCount") or DEFAULT_MAX_APPLICATIONS_PER_RUN)

    existing_jobs = db if isinstance(db, list) else list_autopilot_jobs(db)
    all_passing: list[dict[str, Any]] = []

    for job in raw_jobs:
        passed, skip_reason = evaluate_hard_filters(job, profile, existing_jobs, opts)
        if not passed:
            continue

        # Match Scoring
        match_result = evaluate_job_match(
            job=job,
            profile=profile,
        )
        score = match_result.get("overallScore", 0.0)
        reasons = match_result.get("strongMatches", []) + match_result.get("potentialConcerns", [])

        ranked_job = {
            **job,
            "matchScore": score,
            "matchReasons": reasons,
            "status": AutopilotJobStatus.SCORED.value,
        }
        all_passing.append(ranked_job)

    # Sort descending by matchScore and datePosted
    all_passing.sort(key=lambda j: (j.get("matchScore", 0.0), j.get("datePosted") or ""), reverse=True)

    if min_score > 0:
        qualified = [j for j in all_passing if j.get("matchScore", 0.0) >= min_score]
        if qualified:
            return qualified[:max_apps]

    return all_passing[:max_apps]
