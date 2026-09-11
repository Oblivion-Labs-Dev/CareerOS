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


def role_location_priority_bonus(job: dict[str, Any]) -> float:
    """Candidate-preference ranking bonus implementing strict 4-tier priority:

    Tier 1 (+120.0): Senior Software Engineer in Washington State (Seattle, Bellevue, Redmond, Kirkland, WA)
    Tier 2 (+90.0):  Related Washington SWE/backend/platform role at any level
    Tier 3 (+60.0):  Senior Software Engineer elsewhere in the United States (Remote US / Nationwide)
    Tier 4 (+25.0):  Rest / other qualifying US software engineering roles (e.g. SWE II, Platform)

    Location outranks seniority inside Washington deliberately: a related
    Washington engineering role is preferred over a Senior title somewhere else
    in the country. The bonus is added to the Mistral resume-match score, so
    within a tier the highest-matching posting still applies first.
    """
    title_l = (job.get("title") or "").lower()
    loc_l = (job.get("location") or "").lower()

    # If location is missing from autopilot job payload, check metadata or raw payload
    if not loc_l and "metadata" in job and isinstance(job["metadata"], dict):
        loc_l = (job["metadata"].get("location") or "").lower()

    # Non-software engineering roles must never receive SWE tier priority
    non_swe_markers = (
        "product manager", "program manager", "project manager", "sales engineer",
        "solution architect", "account executive", "designer", "recruiter", "talent",
        "marketing", "human resources", "counsel", "legal", "business analyst",
        "operations manager", "account manager",
    )
    if any(m in title_l for m in non_swe_markers):
        return 0.0

    # Location classification. "Washington, D.C." / "Washington, District of
    # Columbia" are the opposite side of the country from Washington State and
    # must never earn the top location tier — matching the bare substring
    # "washington" previously put D.C. postings at the head of the queue.
    is_dc = any(k in loc_l for k in (
        "district of columbia", "washington, d.c", "washington d.c",
        "washington, dc", "washington dc",
    ))
    is_wa = not is_dc and any(k in loc_l for k in (
        "seattle", "bellevue", "redmond", "kirkland", "spokane",
        "tacoma", ", wa", "wa,", "wa ", "washington",
    ))
    is_us = is_wa or is_dc or any(k in loc_l for k in (
        "united states", "usa", "u.s.", "remote", "us", "remote - us", "remote, us",
    ))

    # Role level classification
    above_senior_markers = (
        "staff", "principal", "distinguished", "fellow", "architect",
        "director", "head of", "vp", "vice president",
    )
    is_above_senior = any(k in title_l for k in above_senior_markers)

    is_senior = (
        any(k in title_l for k in ("senior", "sr.", "sr ", "sr-", "senior swe"))
        and any(k in title_l for k in (
            "software", "backend", "full stack", "frontend", "platform",
            "infrastructure", "systems", "cloud", "security", "data",
            "engineer", "developer",
        ))
        and not is_above_senior
    )

    is_staff_or_principal = (
        is_above_senior
        and any(k in title_l for k in ("staff", "principal"))
        and not any(k in title_l for k in ("director", "vp", "vice president", "head of"))
    )

    is_other_swe = (
        any(k in title_l for k in (
            "software", "backend", "back end", "full stack", "fullstack", "frontend",
            "front end", "platform", "infrastructure", "systems", "distributed",
            "engineer", "developer",
        ))
        and not is_senior
    )

    # Tier 1: Senior Software Engineer in Washington State
    if is_senior and is_wa:
        return 120.0

    # Tier 2: Any related Washington engineering role — Staff/Principal, SWE II,
    # backend/platform/infrastructure. Preferred over an out-of-state Senior
    # title because relocation is the harder constraint here, not the level.
    if is_wa and (is_staff_or_principal or is_other_swe):
        return 90.0

    # Tier 3: Senior Software Engineer elsewhere in the United States
    if is_senior and is_us:
        return 60.0

    # Tier 4: Rest / other US engineering roles (Staff/Principal, SWE II, general SWE)
    if is_us and (is_staff_or_principal or is_other_swe):
        return 25.0

    return 0.0


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

    # A posting with no URL — or one pointing at a careers *index* rather than a
    # specific job — can never be applied to. Without this the executor opens
    # the listing page, fills nothing, and fails with "Submit button not found",
    # burning a full browser session per attempt.
    if not app_url:
        return False, "Posting has no application URL"
    url_path, _, url_query = app_url.partition("?")
    if re.search(r"/(?:jobs|careers|openings|positions)/?$", url_path, flags=re.I):
        # Many boards keep the index path and identify the posting in the query
        # instead (`/en/jobs/?gh_jid=7849003`), so only a URL that names no job
        # anywhere is an index.
        if not re.search(r"=\d{3,}", url_query):
            return False, f"Application URL '{app_url}' is a careers index, not a specific posting"

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
        return False, f"Company '{company}' is a Defense/ITAR contractor (excluded per user preference)"

    # Exclude boards with hard bot protection that block automated headless runs
    if "roblox" in norm_c:
        return False, "Roblox uses Cloudflare Turnstile bot challenges"
    if "okta" in norm_c:
        return False, "Okta uses reCAPTCHA verification"

    if needs_sponsorship and not is_us_citizen:

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


# How much a brand-new posting outranks an otherwise identical old one, and how
# quickly that advantage decays. Freshness is worth less than the
# location/level tier (hundreds of points) but comparable to a few points of
# match score, so it breaks ties between similar jobs without ever promoting a
# poorly-matched posting over a well-matched one.
RECENCY_BONUS_MAX = 12.0
RECENCY_HALF_LIFE_HOURS = 48.0


def posting_recency_bonus(job: dict[str, Any]) -> float:
    """Extra priority for a recently discovered/posted job.

    Stale postings are the single biggest source of wasted attempts: a job
    discovered a day or two ago is frequently already closed by the time
    Autopilot reaches it, which burns a full browser session to learn the link
    now redirects to a careers directory. Ordering the freshest postings first
    means the queue spends its attempts where they can still succeed, and older
    entries are worked through afterwards rather than never.
    """
    from datetime import datetime, timezone

    stamp = (
        job.get("postedAt")
        or job.get("discoveredAt")
        or job.get("queuedAt")
        or job.get("createdAt")
    )
    if not stamp:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0
    if age_hours <= 0:
        return RECENCY_BONUS_MAX
    # Halve the bonus for every half-life the posting has aged.
    return RECENCY_BONUS_MAX * (0.5 ** (age_hours / RECENCY_HALF_LIFE_HOURS))


def queue_priority_score(job: dict[str, Any]) -> float:
    """The single number the persistent queue is ordered by.

    Location/level tier dominates (see ``role_location_priority_bonus``), the
    Mistral resume-match score orders postings inside a tier, and a decaying
    recency bonus puts the freshest postings first so the queue does not spend
    its attempts on links that have already closed.
    """
    return (
        role_location_priority_bonus(job)
        + float(job.get("matchScore") or 0.0)
        + posting_recency_bonus(job)
    )


def filter_and_rank_jobs(
    db: Session | list[dict[str, Any]],
    raw_jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    settings: dict[str, Any] | None = None,
    *,
    precomputed_matches: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Process a list of discovered jobs:

    1. Run hard filters (deterministic)
    2. Attach the Mistral/Ollama resume-vs-JD match (precomputed by the queue
       preprocessor, or scored inline here when the caller has none)
    3. Filter by min match score threshold (with fallback so batch queue never starves)
    4. Sort by location/level tier, then match score, then date posted

    ``maxApplicationsPerRun``/``targetProcessCount`` of 0 (or absent) means *no
    limit* — the persistent queue is deliberately unbounded, and only the E2E
    submission count is capped.
    """
    opts = settings or {}
    min_score = float(opts.get("minMatchScore") or 0.0)
    max_apps = int(opts.get("maxApplicationsPerRun") or opts.get("targetProcessCount") or 0)

    existing_jobs = db if isinstance(db, list) else list_autopilot_jobs(db)
    matches = precomputed_matches or {}
    all_passing: list[dict[str, Any]] = []

    for job in raw_jobs:
        passed, skip_reason = evaluate_hard_filters(job, profile, existing_jobs, opts)
        if not passed:
            continue

        match = matches.get(str(job.get("id") or "")) or job.get("mistralMatch")
        if isinstance(match, dict) and match.get("matchScore") is not None:
            score = float(match.get("matchScore") or 0.0)
            ranked_job = {
                **job,
                "matchScore": score,
                "matchReason": match.get("matchReason", ""),
                "keyMatchingSkills": match.get("keyMatchingSkills") or [],
                "missingSkills": match.get("missingSkills") or [],
                "matchMethod": match.get("matchMethod", "ollama-local"),
                "matchModel": match.get("matchModel", ""),
                # Kept so existing UI/reporting that reads matchReasons still
                # renders something meaningful now that the real explanation is
                # a sentence rather than a bag of keywords.
                "matchReasons": (match.get("keyMatchingSkills") or [])[:8],
                "status": AutopilotJobStatus.SCORED.value,
            }
        else:
            # No Mistral score available (Ollama down, or not preprocessed yet).
            # Fall back to the deterministic heuristic and label it honestly so
            # nothing downstream reports a heuristic number as a model match.
            match_result = evaluate_job_match(job=job, profile=profile)
            score = float(match_result.get("overallScore", 0.0))
            ranked_job = {
                **job,
                "matchScore": score,
                "matchReason": match_result.get("explanation", "") or "Heuristic keyword match (Mistral unavailable).",
                "keyMatchingSkills": match_result.get("strongMatches", [])[:8],
                "missingSkills": match_result.get("missingQualifications", [])[:8],
                "matchMethod": "heuristic",
                "matchReasons": match_result.get("strongMatches", []) + match_result.get("potentialConcerns", []),
                "status": AutopilotJobStatus.SCORED.value,
            }

        ranked_job["queuePriority"] = queue_priority_score(ranked_job)
        all_passing.append(ranked_job)

    # Sort descending by queue priority (tier bonus + match score), then datePosted
    all_passing.sort(key=lambda j: (j.get("queuePriority", 0.0), j.get("datePosted") or ""), reverse=True)

    # minMatchScore orders the queue; it does not remove anything from it.
    #
    # This used to drop every job below the bar whenever at least one job
    # cleared it, which threw away postings for two reasons that are both bad.
    # A job with no score is missing data, not a poor match - when the local
    # model is down or returns unparseable output the score is absent, and
    # filtering on a field that defaults to 0.0 deleted real postings for a
    # reason that had nothing to do with the job. And a genuinely low score is
    # a judgement from a small local model that is often wrong; the user works
    # these lists by hand and may well want to apply anyway.
    #
    # Nothing here weakens the submission bar: a low-scoring job still is not
    # auto-submitted, it just stays visible. Hard eligibility filters above
    # still exclude genuine dead ends.
    if min_score > 0:
        all_passing.sort(
            key=lambda j: (
                float(j.get("matchScore") or 0.0) >= min_score,
                j.get("queuePriority", 0.0),
                j.get("datePosted") or "",
            ),
            reverse=True,
        )

    return all_passing[:max_apps] if max_apps > 0 else all_passing
