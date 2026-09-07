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

    # 3. Role Title Filter (Software Engineering Roles Only)
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
    ]
    is_swe_role = any(kw in title_lower for kw in swe_keywords)
    if not is_swe_role:
        return False, f"Role '{title}' is not a Software Engineering role"

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
    if any(country in job_loc or country in title_lower for country in non_us_indicators):
        return False, f"Location '{job.get('location')}' is outside the United States"

    # Require explicit US indicators or US state/remote patterns if location is present
    # Phrases safe to match as substrings.
    us_indicators = [
        "united states", "usa", "u.s.", "remote - us", "remote (us", "us remote",
        ", us", ", usa", "washington", "california", "new york",
        "texas", "massachusetts", "colorado", "seattle", "austin", "san francisco",
        "boston", "los angeles", "chicago", "new york city"
    ]
    # State abbreviations must be matched as whole tokens, never as substrings —
    # "Budapest, Hungary" contains "ga" (Georgia) and "Poland" contains "la"
    # (Louisiana), which previously let non-US postings pass this check.
    us_state_abbr = {
        "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
        "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
        "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
        "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
        "wi", "wy", "dc",
    }
    if job_loc:
        has_us_marker = any(ind in job_loc for ind in us_indicators)
        if not has_us_marker:
            tokens = {t.strip(" .;|()") for t in re.split(r"[,\s/]+", job_loc)}
            has_us_marker = bool(tokens & us_state_abbr)
        # If it's a generic "remote" with no non-US markers, allow US remote
        if not has_us_marker and "remote" in job_loc:
            has_us_marker = True
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

    if needs_sponsorship and not is_us_citizen:
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
            return False, f"Company '{company}' requires U.S. Citizenship / ITAR clearance (no visa sponsorship provided)"

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

        # Ranking priority (separate from the LLM-derived matchScore shown to
        # the user): "Senior Software Engineer" titles and Seattle-area
        # locations get queued ahead of otherwise-similar matches, per
        # candidate preference — Seattle first, then the rest of the US.
        title_l = (job.get("title") or "").lower()
        loc_l = (job.get("location") or "").lower()
        priority_bonus = 0.0
        if "senior software engineer" in title_l:
            priority_bonus += 15.0
        elif "software engineer" in title_l:
            priority_bonus += 5.0
        if any(k in loc_l for k in ("seattle", ", wa", "washington")):
            priority_bonus += 20.0

        ranked_job = {
            **job,
            "matchScore": score,
            "matchReasons": reasons,
            "status": AutopilotJobStatus.SCORED.value,
            "_priorityScore": score + priority_bonus,
        }
        all_passing.append(ranked_job)

    # Sort descending by priority (matchScore + Seattle/Senior boost), then datePosted
    all_passing.sort(key=lambda j: (j.get("_priorityScore", 0.0), j.get("datePosted") or ""), reverse=True)
    for j in all_passing:
        j.pop("_priorityScore", None)

    if min_score > 0:
        qualified = [j for j in all_passing if j.get("matchScore", 0.0) >= min_score]
        if qualified:
            return qualified[:max_apps]

    return all_passing[:max_apps]
