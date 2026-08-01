"""Qwen-powered resume extraction, ATS analysis, and improvement recommendations."""

from __future__ import annotations

import json
from typing import Any

from app.services.application_assistant.llm_client import LLMClient, create_llm_client
from app.services.application_assistant.persistence import get_settings
from app.services.application_assistant import qwen_activity
from sqlalchemy.orm import Session

SCAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "contact": {
            "type": "object",
            "properties": {
                "fullName": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "location": {"type": "string"},
                "headline": {"type": "string"},
                "yearsExperience": {"type": "string"},
            },
        },
        "skills": {"type": "array", "items": {"type": "string"}},
        "workHistory": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "title": {"type": "string"},
                    "dates": {"type": "string"},
                    "highlights": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "accomplishmentCandidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "bullet": {"type": "string"},
                    "technologies": {"type": "array", "items": {"type": "string"}},
                    "domains": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                },
            },
        },
        "atsKeywordSets": {
            "type": "object",
            "properties": {
                "skills": {"type": "array", "items": {"type": "string"}},
                "tools": {"type": "array", "items": {"type": "string"}},
                "domains": {"type": "array", "items": {"type": "string"}},
                "certifications": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}

RECOMMENDATIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "callLikelihoodSummary": {"type": "string"},
        "topGaps": {"type": "array", "items": {"type": "string"}},
        "addToResume": {"type": "array", "items": {"type": "string"}},
        "emphasizeAccomplishments": {"type": "array", "items": {"type": "string"}},
        "suggestedBullets": {"type": "array", "items": {"type": "string"}},
        "keywordPhrasesToAdd": {"type": "array", "items": {"type": "string"}},
    },
}


def get_qwen_client(db: Session) -> LLMClient:
    settings = get_settings(db)
    llm = settings.get("llm", {})
    if not llm.get("enabled", True):
        return LLMClient(base_url="", model="")
    return create_llm_client(settings)


async def extract_resume_with_qwen(
    db: Session,
    resume_text: str,
    *,
    person_name: str = "",
) -> dict[str, Any]:
    client = get_qwen_client(db)
    if not client.enabled:
        return {"success": False, "error": "Qwen not configured", "data": {}}

    prompt = (
        "Extract structured resume intelligence from the text below.\n"
        "Return JSON only. Be factual — do not invent employers, metrics, or tools not present.\n"
        "Split strong bullets into accomplishmentCandidates with company, title, bullet, technologies, domains.\n"
        "Build atsKeywordSets from explicit resume content (skills, tools, domains, certifications).\n"
        f"Person hint: {person_name or 'unknown'}\n\n"
        f"RESUME TEXT:\n{resume_text[:12000]}"
    )
    system = (
        "You are a resume intelligence extractor for CareerOS. "
        "Output strict JSON matching the schema. Prefer concise bullets. "
        "confidence is 0-1 for each accomplishment candidate."
    )

    qwen_activity.append_log(
        db,
        event_type="resume_scan",
        model=client.model,
        success=True,
        latency_ms=0,
        summary="Extracting resume structure with Qwen…",
    )
    result = await client.complete(prompt, system=system, response_schema=SCAN_SCHEMA)
    if not result.get("success"):
        qwen_activity.append_log(
            db,
            event_type="resume_scan",
            model=client.model,
            success=False,
            latency_ms=0,
            summary="Qwen extract failed",
            error=str(result.get("error") or "unknown"),
        )
        return result

    data = result.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}

    qwen_activity.append_log(
        db,
        event_type="resume_scan",
        model=client.model,
        success=True,
        latency_ms=0,
        summary="Qwen resume extraction complete",
    )
    return {"success": True, "data": data, "usage": result.get("usage")}


async def enrich_ats_keywords_with_qwen(
    db: Session,
    job_description: str,
    job_title: str,
    resume_summary: str,
) -> dict[str, Any]:
    client = get_qwen_client(db)
    if not client.enabled:
        return {"success": False, "error": "Qwen not configured", "data": {}}

    prompt = (
        "Analyze this job posting for ATS keyword sets.\n"
        "Return JSON with: requiredSkills, preferredSkills, actionVerbs, domainTerms, "
        "screeningKeywords (things recruiters/ATS scan for).\n"
        "Use lowercase single tokens or short phrases. No explanations.\n\n"
        f"JOB TITLE: {job_title}\n\n"
        f"JOB DESCRIPTION:\n{job_description[:8000]}\n\n"
        f"RESUME SUMMARY (for contrast):\n{resume_summary[:2000]}"
    )
    system = "You are an ATS keyword analyst. Output strict JSON only."

    result = await client.complete(prompt, system=system)
    if not result.get("success"):
        return result

    data = result.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {"raw": data}
    return {"success": True, "data": data if isinstance(data, dict) else {}}


async def generate_match_recommendations(
    db: Session,
    *,
    job_title: str,
    job_description: str,
    match_result: dict[str, Any],
    accomplishments: list[dict[str, Any]],
) -> dict[str, Any]:
    client = get_qwen_client(db)
    if not client.enabled:
        return {"success": False, "error": "Qwen not configured", "data": {}}

    acc_summary = [
        {
            "id": a.get("id"),
            "title": a.get("title") or a.get("project"),
            "company": a.get("company"),
            "bullet": (a.get("currentBullet") or "")[:200],
        }
        for a in accomplishments[:12]
    ]
    gaps = [m.get("term") for m in match_result.get("missing", [])[:15]]
    unsupported = [m.get("term") for m in match_result.get("unsupported", [])[:10]]

    prompt = (
        "Given a job, match analysis, and resume corpus, recommend how to improve callback likelihood.\n"
        "Be specific and actionable. Do not recommend lying or inventing experience.\n"
        "Return JSON matching the schema.\n\n"
        f"JOB: {job_title}\n"
        f"MATCH SCORE: {match_result.get('overallScore')}%\n"
        f"CALL LIKELIHOOD: {match_result.get('callLikelihood')}\n"
        f"MISSING KEYWORDS: {gaps}\n"
        f"UNSUPPORTED KEYWORDS: {unsupported}\n"
        f"ACCOMPLISHMENTS: {json.dumps(acc_summary)[:4000]}\n\n"
        f"JOB DESCRIPTION:\n{job_description[:5000]}"
    )
    system = (
        "You are a career coach specializing in ATS-safe resume tailoring. "
        "Suggest evidence-backed improvements only. Output strict JSON."
    )

    qwen_activity.append_log(
        db,
        event_type="resume_match",
        model=client.model,
        success=True,
        latency_ms=0,
        summary="Generating match recommendations with Qwen…",
    )
    result = await client.complete(prompt, system=system, response_schema=RECOMMENDATIONS_SCHEMA)
    if not result.get("success"):
        return result

    data = result.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {}
    qwen_activity.append_log(
        db,
        event_type="resume_match",
        model=client.model,
        success=True,
        latency_ms=0,
        summary="Qwen recommendations ready",
    )
    return {"success": True, "data": data if isinstance(data, dict) else {}}
