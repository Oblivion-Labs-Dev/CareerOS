"""Qwen-powered job fit scoring — semantic match against profile, resume, and accomplishments."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from sqlalchemy.orm import Session

from app.services.application_assistant import qwen_activity
from app.services.application_assistant.candidate_match_context import (
    build_candidate_summary_for_llm,
    load_match_context,
    match_sources_used,
)
from app.services.application_assistant.job_matching import match_job
from app.services.application_assistant.llm_client import LLMClient, create_llm_client
from app.services.application_assistant.persistence import get_settings

MATCH_SCORE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overallScore": {"type": "number"},
        "strongMatches": {"type": "array", "items": {"type": "string"}},
        "missingQualifications": {"type": "array", "items": {"type": "string"}},
        "potentialConcerns": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
        "confidence": {"type": "number"},
    },
}

MATCH_SCORE_SYSTEM = """You score how well a candidate fits a job posting.

Use the candidate's resume, work history, skills, and accomplishments — not simple keyword overlap.
Consider required vs preferred qualifications, seniority, domain experience, and transferable skills.

Return JSON only:
{
  "overallScore": 0-100,
  "strongMatches": ["specific strengths that align with the role"],
  "missingQualifications": ["gaps vs stated requirements"],
  "potentialConcerns": ["risks or misalignments, if any"],
  "explanation": "1-3 factual sentences summarizing the fit",
  "confidence": 0.0-1.0
}

Calibration:
- 90-100: exceptional fit, meets nearly all requirements with strong evidence
- 75-89: strong fit, most requirements covered
- 55-74: partial fit, meaningful gaps but some alignment
- 35-54: weak fit, significant gaps
- below 35: poor fit

Do not recommend applying or not applying. Be factual and specific."""


def _truncate(text: str, limit: int) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _score_color(score: float) -> str:
    if score >= 75:
        return "green"
    if score >= 50:
        return "yellow"
    if score >= 30:
        return "orange"
    return "gray"


def _heuristic_match(
    job: dict[str, Any],
    profile: dict[str, Any],
    *,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    result = match_job(
        job,
        profile,
        documents=documents,
        accomplishments=accomplishments,
        **kwargs,
    )
    result["matchMethod"] = "heuristic"
    return result


def _qwen_payload_to_match(
    job: dict[str, Any],
    parsed: dict[str, Any],
    *,
    sources: dict[str, bool],
) -> dict[str, Any]:
    score = max(0.0, min(100.0, float(parsed.get("overallScore", 0))))
    strong = [str(item).strip() for item in (parsed.get("strongMatches") or []) if str(item).strip()][:10]
    missing = [str(item).strip() for item in (parsed.get("missingQualifications") or []) if str(item).strip()][:10]
    concerns = [str(item).strip() for item in (parsed.get("potentialConcerns") or []) if str(item).strip()][:5]
    explanation = str(parsed.get("explanation") or "").strip()
    if not explanation:
        explanation = "Qwen scored this match against your profile and resume."

    return {
        "jobId": job.get("id", ""),
        "overallScore": round(score, 1),
        "requiredCoverage": round(score * 0.9, 1),
        "preferredCoverage": round(score * 0.85, 1),
        "skillOverlap": round(min(100.0, len(strong) * 10.0), 1),
        "experienceAlignment": round(score, 1),
        "seniorityAlignment": round(score * 0.95, 1),
        "locationAlignment": round(score * 0.8, 1),
        "strongMatches": strong,
        "missingQualifications": missing,
        "potentialConcerns": concerns,
        "explanation": explanation,
        "matchSources": sources,
        "matchMethod": "qwen",
        "qwenConfidence": float(parsed.get("confidence", 0.7)),
    }


def qwen_result_to_relevancy(parsed: dict[str, Any]) -> dict[str, Any]:
    score = int(max(0, min(100, round(float(parsed.get("overallScore", 0))))))
    strong = [str(item).strip() for item in (parsed.get("strongMatches") or []) if str(item).strip()]
    return {
        "relevancy_score": score,
        "keywords_matched": strong[:15],
        "color": _score_color(score),
    }


async def score_job_fit_with_qwen(
    client: LLMClient,
    job: dict[str, Any],
    profile: dict[str, Any],
    *,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
    db: Session | None = None,
) -> dict[str, Any] | None:
    """Score one job with Qwen. Returns None when LLM is unavailable or fails."""
    if not client.enabled:
        return None

    candidate_summary = build_candidate_summary_for_llm(profile, documents=documents, accomplishments=accomplishments)
    if not candidate_summary.strip():
        return None

    title = job.get("title") or job.get("roleTitle") or "Unknown role"
    company = job.get("company") or job.get("companyName") or ""
    location = job.get("location") or ""
    description = _truncate(str(job.get("description") or ""), 8000)

    prompt = (
        f"Job title: {title}\n"
        f"Company: {company}\n"
        f"Location: {location}\n\n"
        f"Job description:\n{description or '(no description)'}\n\n"
        f"Candidate profile:\n{_truncate(candidate_summary, 12000)}"
    )

    started = time.perf_counter()
    result = await client.complete(prompt, system=MATCH_SCORE_SYSTEM, response_schema=MATCH_SCORE_SCHEMA)
    latency_ms = int((time.perf_counter() - started) * 1000)

    if db is not None:
        qwen_activity.append_log(
            db,
            event_type="job_match_score",
            model=client.model,
            success=bool(result.get("success")),
            latency_ms=latency_ms,
            summary=f"Match score for {title[:60]}",
            error=str(result.get("error") or ""),
            metadata={"jobId": job.get("id", ""), "company": company[:40]},
        )

    if not result.get("success"):
        return None

    parsed = result.get("data")
    if not isinstance(parsed, dict):
        return None

    sources = match_sources_used(profile, documents=documents, accomplishments=accomplishments)
    return _qwen_payload_to_match(job, parsed, sources=sources)


async def match_job_with_qwen_fallback(
    db: Session,
    job: dict[str, Any],
    profile: dict[str, Any] | None = None,
    *,
    use_qwen: bool = True,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    loaded_profile, loaded_documents, loaded_accomplishments = load_match_context(db)
    effective_profile = profile if profile is not None else loaded_profile
    effective_documents = documents if documents is not None else loaded_documents
    effective_accomplishments = accomplishments if accomplishments is not None else loaded_accomplishments

    if use_qwen:
        settings = get_settings(db)
        client = create_llm_client(settings)
        qwen_match = await score_job_fit_with_qwen(
            client,
            job,
            effective_profile,
            documents=effective_documents,
            accomplishments=effective_accomplishments,
            db=db,
        )
        if qwen_match is not None:
            return qwen_match

    return _heuristic_match(
        job,
        effective_profile,
        documents=effective_documents,
        accomplishments=effective_accomplishments,
        **kwargs,
    )


def match_job_with_qwen_fallback_sync(
    db: Session,
    job: dict[str, Any],
    profile: dict[str, Any] | None = None,
    *,
    use_qwen: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """Sync entry point — uses asyncio.run when no event loop is running."""
    if not use_qwen:
        loaded_profile, documents, accomplishments = load_match_context(db)
        return _heuristic_match(
            job,
            profile if profile is not None else loaded_profile,
            documents=documents,
            accomplishments=accomplishments,
            **kwargs,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            match_job_with_qwen_fallback(db, job, profile, use_qwen=True, **kwargs)
        )

    loaded_profile, documents, accomplishments = load_match_context(db)
    return _heuristic_match(
        job,
        profile if profile is not None else loaded_profile,
        documents=documents,
        accomplishments=accomplishments,
        **kwargs,
    )


async def score_jobs_batch_with_qwen(
    db: Session,
    jobs: list[dict[str, Any]],
    *,
    profile: dict[str, Any] | None = None,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
    concurrency: int = 2,
) -> list[dict[str, Any]]:
    """Score many jobs with Qwen (fallback to heuristic per job). Updates relevancy fields."""
    loaded_profile, loaded_documents, loaded_accomplishments = load_match_context(db)
    effective_profile = profile if profile is not None else loaded_profile
    effective_documents = documents if documents is not None else loaded_documents
    effective_accomplishments = accomplishments if accomplishments is not None else loaded_accomplishments

    settings = get_settings(db)
    client = create_llm_client(settings)
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def score_one(job: dict[str, Any]) -> dict[str, Any]:
        from app.services.job_discover.gap_analysis import attach_gap_to_job

        async with semaphore:
            match = await score_job_fit_with_qwen(
                client,
                job,
                effective_profile,
                documents=effective_documents,
                accomplishments=effective_accomplishments,
                db=db,
            )
            if match is None:
                match = _heuristic_match(
                    job,
                    effective_profile,
                    documents=effective_documents,
                    accomplishments=effective_accomplishments,
                )
            relevancy = {
                "relevancy_score": int(round(match.get("overallScore", 0))),
                "keywords_matched": match.get("strongMatches") or [],
                "color": _score_color(float(match.get("overallScore", 0))),
            }
            updated = {
                **job,
                "relevancyScore": relevancy["relevancy_score"],
                "keywordsMatched": relevancy["keywords_matched"],
                "color": relevancy["color"],
                "matchMethod": match.get("matchMethod", "heuristic"),
            }
            return attach_gap_to_job(
                updated,
                match,
                effective_profile,
                documents=effective_documents,
                accomplishments=effective_accomplishments,
            )

    return list(await asyncio.gather(*(score_one(job) for job in jobs)))
