"""Precomputed job gap analysis for the discover side panel."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.services.application_assistant.candidate_match_context import (
    build_candidate_skill_terms,
    extract_keywords,
)
from app.services.application_assistant.job_matching import parse_job_qualifications


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _is_valid_gap_term(term: str) -> bool:
    cleaned = term.strip().lower().rstrip(".")
    if len(cleaned) < 3 or len(cleaned) > 40:
        return False
    return bool(re.fullmatch(r"[a-z0-9+#]+", cleaned))


def _description_highlights(description: str, *, limit: int = 10) -> list[str]:
    lines: list[str] = []
    for raw in description.split("\n"):
        cleaned = raw.strip().lstrip("•-*·").strip()
        if len(cleaned) < 20 or len(cleaned) > 320:
            continue
        if cleaned.lower().startswith(("about ", "we are", "our team", "the role")):
            lines.append(cleaned)
        elif any(token in cleaned.lower() for token in ("required", "must", "experience", "years", "skill", "proficiency")):
            lines.append(cleaned)
        elif len(lines) < 3:
            lines.append(cleaned)
        if len(lines) >= limit:
            break
    return lines


def _keyword_gaps(
    job: dict[str, Any],
    profile: dict[str, Any],
    documents: dict[str, Any] | None,
    accomplishments: list[dict[str, Any]] | None,
) -> list[str]:
    title = str(job.get("title") or "")
    description = str(job.get("description") or "")
    job_terms = extract_keywords(f"{title} {description}")
    candidate_terms = build_candidate_skill_terms(profile, documents=documents, accomplishments=accomplishments)
    missing_terms = sorted(job_terms - candidate_terms, key=len, reverse=True)
    gaps: list[str] = []
    for term in missing_terms:
        if not _is_valid_gap_term(term):
            continue
        gaps.append(term.strip().lower().rstrip("."))
        if len(gaps) >= 12:
            break
    return gaps


def compose_gap_analysis(
    job: dict[str, Any],
    match: dict[str, Any],
    profile: dict[str, Any],
    *,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
    lightweight: bool = False,
) -> dict[str, Any]:
    """Build gap panel payload from a precomputed match result."""
    description = str(job.get("description") or "")
    if lightweight:
        required = _description_highlights(description, limit=6)
        preferred: list[str] = []
    else:
        qualifications = parse_job_qualifications(description)
        required = qualifications.get("required") or []
        preferred = qualifications.get("preferred") or []
        if not required and not preferred:
            required = _description_highlights(description)

    strong = [str(item).strip() for item in (match.get("strongMatches") or []) if str(item).strip()]
    if not strong:
        strong = [str(item).strip() for item in (job.get("keywordsMatched") or []) if str(item).strip()][:12]

    missing: list[str] = []
    for item in match.get("missingQualifications") or []:
        text = str(item).strip()
        if not text:
            continue
        if _is_valid_gap_term(text) or (len(text) >= 12 and " " in text):
            missing.append(text.rstrip("."))
    if not missing:
        missing = _keyword_gaps(job, profile, documents, accomplishments)

    list_score = float(job.get("relevancyScore") or 0)
    analysis_score = float(match.get("overallScore") or 0)
    score = list_score if list_score > 0 else analysis_score
    gap = max(0.0, min(100.0, 100.0 - score))
    preview = description.strip()
    if len(preview) > 1800:
        preview = preview[:1797].rstrip() + "..."

    return {
        "overallScore": round(score, 1),
        "gapPercent": round(gap, 1),
        "strongMatches": strong[:15],
        "missingQualifications": missing[:15],
        "potentialConcerns": match.get("potentialConcerns") or [],
        "explanation": match.get("explanation") or "",
        "matchMethod": match.get("matchMethod") or "heuristic",
        "matchSources": match.get("matchSources") or {},
        "jobRequirements": {
            "required": required[:15],
            "preferred": preferred[:10],
        },
        "descriptionPreview": preview,
    }


def attach_gap_to_job(
    job: dict[str, Any],
    match: dict[str, Any],
    profile: dict[str, Any],
    *,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
    analyzed_at: str | None = None,
    lightweight: bool = False,
) -> dict[str, Any]:
    """Attach precomputed gap analysis fields to a discover job."""
    analysis = compose_gap_analysis(
        job,
        match,
        profile,
        documents=documents,
        accomplishments=accomplishments,
        lightweight=lightweight,
    )
    return {
        **job,
        "gapAnalysis": analysis,
        "gapAnalysisAt": analyzed_at or _utc_now(),
        "gapAnalysisMethod": match.get("matchMethod") or "heuristic",
    }
