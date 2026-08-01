"""Deterministic job matching against profile, resume, and accomplishments."""

from __future__ import annotations

import re
from typing import Any

from app.services.application_assistant.candidate_match_context import (
    build_candidate_skill_terms,
    extract_keywords,
    match_sources_used,
)


def _extract_keywords(text: str) -> set[str]:
    return extract_keywords(text)


def _parse_qualifications(description: str) -> tuple[list[str], list[str]]:
    """Parse required and preferred qualifications from job description."""
    required: list[str] = []
    preferred: list[str] = []

    lines = description.split("\n")
    current_section = "general"
    for line in lines:
        lower = line.lower().strip()
        if re.search(r"required|must have|minimum|qualifications", lower):
            current_section = "required"
            continue
        if re.search(r"preferred|nice to have|bonus|desired", lower):
            current_section = "preferred"
            continue
        cleaned = line.strip().lstrip("•-*·").strip()
        if len(cleaned) < 10:
            continue
        if current_section == "required":
            required.append(cleaned)
        elif current_section == "preferred":
            preferred.append(cleaned)

    return required, preferred


def parse_job_qualifications(description: str) -> dict[str, list[str]]:
    """Parse required and preferred qualifications from a job description."""
    required, preferred = _parse_qualifications(description)
    return {"required": required, "preferred": preferred}


def _seniority_level(title: str) -> str:
    """Detect seniority level from job title."""
    lower = title.lower()
    if re.search(r"\b(intern|internship)\b", lower):
        return "intern"
    if re.search(r"\b(junior|jr\.?|entry)\b", lower):
        return "junior"
    if re.search(r"\b(senior|sr\.?|staff|principal|lead|architect|director|vp|head)\b", lower):
        return "senior"
    return "mid"


def match_job(
    job: dict[str, Any],
    profile: dict[str, Any],
    *,
    location_preferences: list[str] | None = None,
    workplace_preference: str = "",
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Match a job against profile + optional resume/accomplishment content."""
    description = job.get("description", "")
    title = job.get("title", "")
    location = job.get("location", "")

    required, preferred = _parse_qualifications(description)
    if job.get("requiredQualifications"):
        required = job["requiredQualifications"]
    if job.get("preferredQualifications"):
        preferred = job["preferredQualifications"]

    profile_skills = build_candidate_skill_terms(
        profile,
        documents=documents,
        accomplishments=accomplishments,
    )
    sources = match_sources_used(profile, documents=documents, accomplishments=accomplishments)
    job_keywords = _extract_keywords(f"{title} {description}")

    overlap = profile_skills & job_keywords
    skill_overlap = len(overlap) / max(len(job_keywords), 1) * 100

    required_matches = []
    required_missing = []
    for qual in required:
        qual_keywords = _extract_keywords(qual)
        if qual_keywords & profile_skills:
            required_matches.append(qual)
        else:
            required_missing.append(qual)
    required_coverage = len(required_matches) / max(len(required), 1) * 100

    preferred_matches = []
    for qual in preferred:
        qual_keywords = _extract_keywords(qual)
        if qual_keywords & profile_skills:
            preferred_matches.append(qual)
    preferred_coverage = len(preferred_matches) / max(len(preferred), 1) * 100

    years_str = profile.get("yearsExperience", "0")
    try:
        profile_years = int(re.search(r"\d+", years_str).group()) if re.search(r"\d+", years_str) else 0
    except (AttributeError, ValueError):
        profile_years = 0

    exp_match = re.search(r"(\d+)\+?\s*years?", description, re.I)
    required_years = int(exp_match.group(1)) if exp_match else 0
    if required_years == 0:
        experience_alignment = 80.0
    elif profile_years >= required_years:
        experience_alignment = 100.0
    elif profile_years >= required_years - 2:
        experience_alignment = 70.0
    else:
        experience_alignment = max(0, profile_years / required_years * 50)

    job_seniority = _seniority_level(title)
    profile_title = profile.get("currentTitle", "") or profile.get("targetRole", "")
    profile_seniority = _seniority_level(profile_title)
    seniority_map = {"intern": 0, "junior": 1, "mid": 2, "senior": 3}
    job_level = seniority_map.get(job_seniority, 2)
    profile_level = seniority_map.get(profile_seniority, 2)
    seniority_diff = abs(job_level - profile_level)
    seniority_alignment = max(0, 100 - seniority_diff * 30)

    location_alignment = 50.0
    if location_preferences and location:
        loc_lower = location.lower()
        for pref in location_preferences:
            if pref.lower() in loc_lower:
                location_alignment = 100.0
                break
        if "remote" in loc_lower and workplace_preference in ("remote", "any", ""):
            location_alignment = max(location_alignment, 90.0)

    overall = (
        required_coverage * 0.35
        + skill_overlap * 0.25
        + experience_alignment * 0.15
        + seniority_alignment * 0.10
        + preferred_coverage * 0.10
        + location_alignment * 0.05
    )

    strong_matches = list(overlap)[:10]
    concerns = []
    if required_missing:
        concerns.append(f"Missing {len(required_missing)} required qualification(s)")
    if seniority_diff >= 2:
        concerns.append(f"Seniority gap: profile is {profile_seniority}, job is {job_seniority}")

    explanation_parts = []
    if sources.get("resume"):
        explanation_parts.append("Compared against your uploaded resume")
    elif sources.get("accomplishments"):
        explanation_parts.append("Compared against your resume accomplishments")
    else:
        explanation_parts.append("Compared against profile fields only — upload a resume for stronger matching")
    if strong_matches:
        explanation_parts.append(f"Strong skill overlap: {', '.join(list(strong_matches)[:5])}")
    if required_coverage >= 70:
        explanation_parts.append(f"Covers {len(required_matches)}/{len(required)} required qualifications")
    elif required:
        explanation_parts.append(f"Only {len(required_matches)}/{len(required)} required qualifications matched")
    if experience_alignment >= 80:
        explanation_parts.append("Experience level aligns well")
    if location_alignment >= 80:
        explanation_parts.append("Location preference match")

    return {
        "jobId": job.get("id", ""),
        "overallScore": round(min(100, overall), 1),
        "requiredCoverage": round(required_coverage, 1),
        "preferredCoverage": round(preferred_coverage, 1),
        "skillOverlap": round(skill_overlap, 1),
        "experienceAlignment": round(experience_alignment, 1),
        "seniorityAlignment": round(seniority_alignment, 1),
        "locationAlignment": round(location_alignment, 1),
        "strongMatches": strong_matches,
        "missingQualifications": required_missing[:10],
        "potentialConcerns": concerns,
        "explanation": ". ".join(explanation_parts) if explanation_parts else "Limited match data available",
        "matchSources": sources,
    }
