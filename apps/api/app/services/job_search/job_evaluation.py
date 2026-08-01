"""Multi-dimension job fit evaluation (ai-job-search 04-job-evaluation framework)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.services.job_discover import relevancy_engine
from app.services.job_search.methodology import DIMENSION_WEIGHTS, verdict_from_score
from app.services.job_search.posting_legitimacy import check_posting_legitimacy

RELOCATION_PATTERNS = [
    r"\brelocation\s+required\b",
    r"\bmust\s+relocate\b",
    r"\bon[\s-]?site\s+only\b",
    r"\bno\s+remote\b",
]

CITIZENSHIP_FAIL_PATTERNS = [
    r"\b(?:u\.?s\.?\s+)?citizen(?:ship)?\s+required\b",
    r"\bsecurity\s+clearance\s+required\b",
    r"\bactive\s+top\s+secret\b",
    r"\beligible\s+to\s+work\s+in\s+the\s+u\.?s\.?\s+without\s+sponsorship\b",
]

VISA_PASS_PATTERNS = [
    r"\bvisa\s+sponsor",
    r"\bh1b\s+sponsor",
    r"\bwe\s+sponsor\b",
    r"\bwork\s+authorization\s+sponsor",
]

BEHAVIORAL_KEYWORDS = [
    "communication",
    "collaboration",
    "stakeholder",
    "cross-functional",
    "leadership",
    "mentor",
    "team",
    "culture",
    "customer",
]


def _profile_field(profile: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = profile.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def _normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    skills = profile.get("skills") or profile.get("Skills") or ""
    if isinstance(skills, list):
        skills_text = ", ".join(str(item) for item in skills)
    else:
        skills_text = str(skills)
    return {
        "current_title": _profile_field(profile, "currentTitle", "current_title", "title"),
        "target_role": _profile_field(profile, "targetRole", "target_role"),
        "years_experience": int(profile.get("yearsExperience") or profile.get("years_experience") or 0),
        "skills": skills_text,
        "city": _profile_field(profile, "city"),
        "state": _profile_field(profile, "state"),
        "work_authorization": _profile_field(profile, "workAuthorization", "work_authorization").lower(),
        "remote_preference": _profile_field(profile, "remotePreference", "remote_preference").lower(),
    }


def check_eligibility(posting_text: str, profile: dict[str, Any]) -> dict[str, Any]:
    text = posting_text.lower()
    normalized = _normalize_profile(profile)

    for pattern in CITIZENSHIP_FAIL_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return {"eligible": False, "reason": f"Hard filter matched: {pattern}", "verified": True}

    for pattern in VISA_PASS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return {"eligible": True, "reason": "Posting mentions sponsorship", "verified": True}

    auth = normalized["work_authorization"]
    if auth and any(token in auth for token in ("sponsor", "h1b", "opt", "visa")):
        if not any(re.search(p, text, re.IGNORECASE) for p in VISA_PASS_PATTERNS):
            return {
                "eligible": True,
                "reason": "Work authorization needs verification — posting silent on sponsorship",
                "verified": False,
            }

    return {"eligible": True, "reason": "No eligibility blockers detected", "verified": True}


def _score_location(job: dict[str, Any], profile: dict[str, Any]) -> tuple[str, list[str]]:
    location = str(job.get("location") or "").lower()
    description = str(job.get("description") or "").lower()
    combined = f"{location} {description}"
    flags: list[str] = []

    for pattern in RELOCATION_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return "FAIL", ["Relocation or on-site requirement detected (deal-breaker)"]

    if "travel" in combined and re.search(r"\b(?:50|75|100)\s*%\s*travel\b", combined):
        flags.append("Heavy travel requirement")
        return "FLAG", flags

    normalized = _normalize_profile(profile)
    remote_pref = normalized["remote_preference"]
    if remote_pref in {"remote", "hybrid"} and re.search(r"\bon[\s-]?site\b", combined) and "remote" not in combined:
        flags.append("On-site emphasis may conflict with remote preference")

    user_city = normalized["city"].lower()
    user_state = normalized["state"].lower()
    if user_city and user_city in location:
        flags.append("Location matches profile city")
    elif user_state and user_state in location:
        flags.append("Location matches profile state")
    elif "remote" in combined:
        flags.append("Remote-friendly posting")

    return "PASS", flags


def _score_experience(job: dict[str, Any], profile: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    title = str(job.get("title") or job.get("roleTitle") or "")
    normalized = _normalize_profile(profile)
    user_years = normalized["years_experience"]
    seniority_min, seniority_max = relevancy_engine._detect_seniority(title)

    strengths: list[str] = []
    gaps: list[str] = []

    if user_years >= seniority_min and user_years <= seniority_max + 2:
        score = 85
        strengths.append(f"Experience ({user_years}y) aligns with role seniority")
    elif user_years < seniority_min:
        gap = seniority_min - user_years
        score = max(25, 70 - gap * 15)
        gaps.append(f"Role expects ~{seniority_min}+ years; profile shows {user_years}")
    else:
        score = 75
        strengths.append("Experience exceeds minimum seniority band")

    return score, strengths, gaps


def _score_behavioral(description: str) -> tuple[int, list[str], list[str]]:
    text = description.lower()
    hits = [kw for kw in BEHAVIORAL_KEYWORDS if kw in text]
    if not hits:
        return 65, ["No strong behavioral signals in posting"], []
    score = min(95, 55 + len(hits) * 8)
    return score, [f"Behavioral emphasis: {', '.join(hits[:3])}"], []


def _score_career(job: dict[str, Any], profile: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    normalized = _normalize_profile(profile)
    title = str(job.get("title") or "")
    target = normalized["target_role"] or normalized["current_title"]
    strengths: list[str] = []
    gaps: list[str] = []

    if not target:
        return 60, [], ["No target role set in profile"]

    target_words = {w for w in target.lower().split() if len(w) > 2}
    title_words = {w for w in title.lower().split() if len(w) > 2}
    overlap = target_words & title_words
    if overlap:
        score = min(95, 70 + len(overlap) * 10)
        strengths.append(f"Title aligns with target role ({', '.join(sorted(overlap))})")
    else:
        score = 45
        gaps.append(f"Title diverges from target role ({target})")

    dept = str(job.get("department") or "").lower()
    if dept and any(word in dept for word in target_words):
        score = min(100, score + 10)
        strengths.append("Department aligns with career direction")

    return score, strengths, gaps


def evaluate_job_fit(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Return multi-dimension fit evaluation for a single job."""
    normalized = _normalize_profile(profile)
    relevancy_job = {
        "title": job.get("title") or job.get("roleTitle") or "",
        "description": job.get("description") or job.get("jobDescription") or "",
        "location": job.get("location") or "",
        "department": job.get("department") or "",
    }
    relevancy_profile = {
        "current_title": normalized["current_title"],
        "skills": normalized["skills"],
        "years_experience": normalized["years_experience"],
        "city": normalized["city"],
        "state": normalized["state"],
    }
    relevancy = relevancy_engine.score_job(relevancy_job, relevancy_profile)
    technical = int(relevancy["relevancy_score"])

    description = str(relevancy_job["description"])
    posting_text = f"{relevancy_job['title']} {description} {relevancy_job['location']}"

    eligibility = check_eligibility(posting_text, profile)
    location_verdict, location_flags = _score_location(job, profile)
    experience, exp_strengths, exp_gaps = _score_experience(job, profile)
    behavioral, beh_strengths, beh_gaps = _score_behavioral(description)
    career, car_strengths, car_gaps = _score_career(job, profile)
    legitimacy = check_posting_legitimacy(
        title=str(relevancy_job["title"]),
        description=description,
        url=str(job.get("url") or ""),
        company=str(job.get("companyName") or job.get("company") or ""),
    )

    strengths = (relevancy.get("keywords_matched") or [])[:2]
    strengths.extend(exp_strengths[:1])
    strengths.extend(beh_strengths[:1])
    strengths.extend(car_strengths[:1])
    strengths = [str(item) for item in strengths[:3]]

    gaps = list(exp_gaps[:1]) + list(beh_gaps[:1]) + list(car_gaps[:1])
    if technical < 50:
        gaps.insert(0, "Limited skill/title overlap with posting")
    if legitimacy["verdict"] == "suspicious":
        gaps.insert(0, "Posting legitimacy concerns (Block G)")
    elif legitimacy["verdict"] == "caution" and legitimacy.get("signals"):
        gaps.append(str(legitimacy["signals"][0]))
    gaps = gaps[:3]

    if not eligibility["eligible"]:
        overall = 0
        verdict = "Poor Fit"
    elif location_verdict == "FAIL":
        overall = min(technical, 44)
        verdict = "Weak Fit"
    else:
        overall = round(
            technical * DIMENSION_WEIGHTS["technical"]
            + experience * DIMENSION_WEIGHTS["experience"]
            + behavioral * DIMENSION_WEIGHTS["behavioral"]
            + career * DIMENSION_WEIGHTS["career"]
        )
        verdict = verdict_from_score(overall)

    return {
        "eligible": eligibility["eligible"],
        "eligibilityReason": eligibility["reason"],
        "eligibilityVerified": eligibility["verified"],
        "scores": {
            "technical": technical,
            "experience": experience,
            "behavioral": behavioral,
            "career": career,
        },
        "location": location_verdict,
        "locationFlags": location_flags,
        "overallScore": overall,
        "verdict": verdict,
        "strengths": strengths,
        "gaps": gaps,
        "keywordsMatched": relevancy.get("keywords_matched") or [],
        "legitimacy": legitimacy,
        "evaluatedAt": datetime.now(timezone.utc).isoformat(),
    }


def rank_jobs(jobs: list[dict[str, Any]], profile: dict[str, Any], *, exclude_applied: set[str] | None = None) -> list[dict[str, Any]]:
    """Batch rank jobs; excludes location FAIL and ineligible; sorts by overall score desc."""
    exclude = exclude_applied or set()
    ranked: list[dict[str, Any]] = []

    for job in jobs:
        key = str(job.get("id") or job.get("url") or "")
        company = str(job.get("companyName") or job.get("company") or "").strip().lower()
        title = str(job.get("title") or job.get("roleTitle") or "").strip().lower()
        dedupe_key = f"{company}|{title}"
        if dedupe_key in exclude:
            continue

        evaluation = evaluate_job_fit(job, profile)
        if not evaluation["eligible"] or evaluation["location"] == "FAIL":
            continue
        if evaluation.get("legitimacy", {}).get("verdict") == "suspicious":
            continue

        ranked.append(
            {
                **job,
                "fitEvaluation": evaluation,
                "rankScore": evaluation["overallScore"],
                "rankVerdict": evaluation["verdict"],
                "rankDate": evaluation["evaluatedAt"],
            }
        )

    ranked.sort(key=lambda item: item.get("rankScore") or 0, reverse=True)
    return ranked
