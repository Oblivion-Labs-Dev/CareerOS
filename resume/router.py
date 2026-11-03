"""FastAPI routes for the resume service.

Paths are kept identical to the pre-refactor routers (no service prefix is added
here); ``main.py`` includes this router without a prefix so existing
frontend/extension calls keep resolving. These handlers were moved verbatim out
of ``apps/api/app/routers/api.py`` as part of the modular-monolith refactor; the
resume-intelligence sub-router (``/resume-intelligence/*``) is included from
``resume.intelligence_routes``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.config import settings
from app.db.store import (
    delete_entity,
    get_entity,
    get_kv,
    list_entities,
    new_id,
    now_iso,
    set_kv,
    upsert_entity,
)
from autopilot.persistence import get_settings as get_aa_settings
from intelligence.llm.client import analyze_accomplishment, generate_resume_bullets_for_job
from jobs.discovery import store as job_discover
from resume import resume_profiles as resume_profiles_service
from resume.ats_score import compute_ats_score
from resume.intelligence_routes import router as resume_intelligence_router
from resume.parsers.pdf_parser import parse_resume_into_profile
from resume.tailoring import (
    TAILORING_TONE_BY_MODE,
    build_tailoring_diff,
)
from shared.deps import db_session

router = APIRouter()


class ResumePayload(BaseModel):
    resume: dict[str, Any]


class ParseResumePayload(BaseModel):
    force: bool = False


class AccomplishmentPayload(BaseModel):
    accomplishment: dict[str, Any]


class AiGeneratePayload(BaseModel):
    description: str
    currentData: dict[str, Any] | None = None


class ResumeGeneratePayload(BaseModel):
    mode: str = Field(default="honest", pattern="^(off|honest|aggressive)$")
    accomplishmentIds: list[str]
    targetCompany: str
    targetRole: str
    jobDescription: str
    experienceLevel: str = "Senior"
    tone: str = "professional"
    maxPages: int = 1
    targetAtsScore: int = 85


class ResumeTailorPayload(BaseModel):
    accomplishmentIds: list[str] | None = None
    jobId: str | None = None
    targetCompany: str = ""
    targetRole: str = ""
    jobDescription: str = ""
    experienceLevel: str = "Senior"
    tone: str = "professional"
    maxPages: int = 1
    targetAtsScore: int = 85
    mode: str | None = None


class ResumeTailorApprovePayload(BaseModel):
    mode: str
    jobId: str | None = None
    targetCompany: str = ""
    targetRole: str = ""
    bullets: list[dict[str, Any]] = Field(default_factory=list)
    skillsList: list[str] = Field(default_factory=list)


class ResumeProfileCreatePayload(BaseModel):
    name: str
    resume: dict[str, Any] | None = None


class ResumeProfilePatchPayload(BaseModel):
    name: str | None = None
    resume: dict[str, Any] | None = None


class ResumeStudioPayload(BaseModel):
    useSemantic: bool | None = None
    mode: str = Field(default="honest", pattern="^(off|honest|aggressive)$")
    jobDescription: str = Field(min_length=40, max_length=40000)
    targetRole: str = Field(default="", max_length=200)
    targetCompany: str = Field(default="", max_length=200)


class AnswerQuestionPayload(BaseModel):
    questionId: str
    answer: str


@router.post("/documents/resume")
def upload_resume(payload: ResumePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    documents = get_kv(db, "documents") or {"defaultResume": None, "defaultCoverLetter": None}
    resume = {
        **payload.resume,
        "id": payload.resume.get("id") or new_id("resume_"),
        "updatedAt": now_iso(),
    }
    documents["defaultResume"] = resume
    set_kv(db, "documents", documents)
    return {"success": True, "resume": resume}


@router.get("/documents/resume")
def get_resume(db: Session = Depends(db_session)) -> dict[str, Any]:
    documents = get_kv(db, "documents") or {}
    return {"resume": documents.get("defaultResume")}


@router.post("/api/parse-resume")
async def parse_resume_route(payload: ParseResumePayload | None = None, db: Session = Depends(db_session)) -> dict[str, Any]:
    profile = get_kv(db, "profile") or {}
    documents = get_kv(db, "documents") or {}
    try:
        result = parse_resume_into_profile(profile, documents, force=bool(payload and payload.force))
        set_kv(db, "profile", result["profile"])
        db.commit()
        tier1 = await job_discover.start_tier1_rescore_background(force=True)
        return {"success": True, **result, "tier1Rescore": tier1}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/profile/resume-profiles")
def list_resume_profiles_route(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "profiles": resume_profiles_service.list_resume_profiles(db)}


@router.post("/profile/resume-profiles")
def create_resume_profile_route(payload: ResumeProfileCreatePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    profile = resume_profiles_service.create_resume_profile(db, payload.name, payload.resume)
    return {"success": True, "profile": profile}


@router.patch("/profile/resume-profiles/{profile_id}")
def patch_resume_profile_route(profile_id: str, payload: ResumeProfilePatchPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    patch = payload.model_dump(exclude_none=True)
    updated = resume_profiles_service.update_resume_profile(db, profile_id, patch)
    if not updated:
        raise HTTPException(status_code=404, detail="Resume profile not found")
    return {"success": True, "profile": updated}


@router.delete("/profile/resume-profiles/{profile_id}")
def delete_resume_profile_route(profile_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    deleted = resume_profiles_service.delete_resume_profile(db, profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Resume profile not found")
    return {"success": True}


@router.post("/profile/resume-profiles/{profile_id}/set-default")
def set_default_resume_profile_route(profile_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    updated = resume_profiles_service.set_default_resume_profile(db, profile_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Resume profile not found")
    return {"success": True, "profile": updated}


@router.get("/resume/ats-score")
def resume_ats_score_route(profileId: str = "", jobId: str = "", db: Session = Depends(db_session)) -> dict[str, Any]:
    if profileId:
        profile = resume_profiles_service.get_resume_profile(db, profileId)
        if not profile:
            raise HTTPException(status_code=404, detail="Resume profile not found")
        resume = profile.get("resume")
    else:
        documents = get_kv(db, "documents") or {}
        resume = documents.get("defaultResume")

    job = None
    if jobId:
        job = get_entity(db, "job", jobId) or get_entity(db, "aa_discovered_job", jobId)

    return {"success": True, **compute_ats_score(resume, job)}


@router.post("/resume/export-pdf")
def export_local_resume(payload: dict[str, Any] = Body(...), db: Session = Depends(db_session)):
    from fastapi.responses import Response
    from resume.composer import validate_sources, with_profile
    from resume.local_document import render
    result = payload.get("result") or {}
    records = with_profile(list_entities(db, "accomplishment"), get_kv(db, "profile") or {})
    problems = validate_sources(result, records)
    if problems:
        raise HTTPException(status_code=409, detail=problems)
    # Draft download does not certify claims or enable application submission.
    try:
        data = render(result, get_kv(db, "profile") or {}, draft=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="resume-draft.pdf"'})


@router.post("/resume/generate")
async def generate_resume_route(payload: ResumeGeneratePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    requested_ids = list(dict.fromkeys(payload.accomplishmentIds))

    from resume.composer import with_profile
    all_accs = with_profile(list_entities(db, "accomplishment"), get_kv(db, "profile") or {})
    selected_accs = [a for a in all_accs if not requested_ids or a.get("id") in requested_ids]
    selected_ids = {str(accomplishment.get("id")) for accomplishment in selected_accs}
    missing_ids = [accomplishment_id for accomplishment_id in requested_ids if accomplishment_id not in selected_ids]
    if missing_ids:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "One or more selected accomplishments no longer exist",
                "missingAccomplishmentIds": missing_ids,
            },
        )

    try:
        result = await generate_resume_bullets_for_job(
            accomplishments=selected_accs,
            target_company=payload.targetCompany,
            target_role=payload.targetRole,
            job_description=payload.jobDescription,
            experience_level=payload.experienceLevel,
            tone=payload.tone,
            max_pages=payload.maxPages,
            target_ats=payload.targetAtsScore,
            mode=payload.mode,
            tailoring_config=(get_kv(db, "profile") or {}).get("resumeTailoringConfig"),
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="Resume generation is temporarily unavailable. No synthetic fallback content was returned.",
        )
    from resume.local_document import document_text
    result["content"] = document_text(result, get_kv(db, "profile") or {})
    return {"success": True, "result": result}


@router.post("/resume/studio")
def generate_resume_studio(payload: ResumeStudioPayload, db: Session = Depends(db_session)):
    from resume.studio import generate_studio
    try:
        return {"success": True, **generate_studio(list_entities(db, "accomplishment"), get_kv(db, "profile") or {},
                    payload.jobDescription, payload.targetRole, payload.targetCompany, payload.mode, payload.useSemantic)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/resume/tailor")
async def tailor_resume_route(payload: ResumeTailorPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Job-specific bullet tailoring, gated by the Off/Honest/Aggressive dial.

    Always returns a diff (original vs. tailored, per bullet) — never writes
    anything. The caller applies the result explicitly via a separate accept step.
    """
    mode = payload.mode or get_aa_settings(db).get("tailoringMode", "honest")
    if mode not in TAILORING_TONE_BY_MODE:
        mode = "honest"

    from resume.composer import with_profile
    all_accs = with_profile(list_entities(db, "accomplishment"), get_kv(db, "profile") or {})
    if payload.accomplishmentIds:
        requested_ids = set(payload.accomplishmentIds)
        selected_accs = [a for a in all_accs if not requested_ids or a.get("id") in requested_ids]
    else:
        selected_accs = all_accs

    if mode == "off":
        from resume.minimal_tailoring import tailor, TailoringConfig
        try:
            baseline_result = tailor([], "", mode="off", config=TailoringConfig(use_semantic=False, weak_relevance=0, max_replacement_fraction=0, reorder_threshold=1))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"success": True, "result": build_tailoring_diff([], baseline_result, mode)}

    target_company = payload.targetCompany
    target_role = payload.targetRole
    job_description = payload.jobDescription
    if payload.jobId and not (target_company and target_role and job_description):
        job = get_entity(db, "job", payload.jobId) or get_entity(db, "aa_discovered_job", payload.jobId)
        if job:
            target_company = target_company or str(job.get("companyName") or job.get("company") or "")
            target_role = target_role or str(job.get("title") or job.get("roleTitle") or "")
            job_description = job_description or str(job.get("description") or "")


    from profile.memory import active_memory_text

    try:
        result = await generate_resume_bullets_for_job(
            accomplishments=selected_accs,
            target_company=target_company,
            target_role=target_role,
            job_description=job_description,
            experience_level=payload.experienceLevel,
            tone=TAILORING_TONE_BY_MODE[mode],
            max_pages=payload.maxPages,
            target_ats=payload.targetAtsScore,
            mode=mode,
            extra_instructions=active_memory_text(db),
            tailoring_config=(get_kv(db, "profile") or {}).get("resumeTailoringConfig"),
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="Resume tailoring is temporarily unavailable. No synthetic fallback content was returned.",
        )
    return {"success": True, "result": build_tailoring_diff(selected_accs, result, mode)}


@router.post("/resume/tailor/approve")
def approve_resume_tailoring_route(payload: ResumeTailorApprovePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Persist an explicitly-approved tailoring result. Never called implicitly by /resume/tailor."""
    record = upsert_entity(
        db,
        "resume_tailoring",
        {
            "id": new_id("tailor_"),
            "mode": payload.mode,
            "jobId": payload.jobId,
            "targetCompany": payload.targetCompany,
            "targetRole": payload.targetRole,
            "bullets": payload.bullets,
            "skillsList": payload.skillsList,
            "approvedAt": now_iso(),
        },
    )
    return {"success": True, "tailoring": record}


@router.get("/resume/tailor/history")
def list_resume_tailoring_route(db: Session = Depends(db_session)) -> dict[str, Any]:
    records = sorted(list_entities(db, "resume_tailoring"), key=lambda r: r.get("approvedAt", ""), reverse=True)
    return {"success": True, "tailorings": records}


@router.get("/accomplishments")
def list_accomplishments_route(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"accomplishments": list_entities(db, "accomplishment")}


@router.post("/accomplishments")
def save_accomplishment_route(payload: AccomplishmentPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    previous = get_entity(db, "accomplishment", payload.accomplishment.get("id")) if payload.accomplishment.get("id") else None
    updated = {**(previous or {}), **payload.accomplishment}
    incoming = payload.accomplishment
    if "current" in (incoming.get("resumeEvolution") or {}):
        updated["currentBullet"] = incoming["resumeEvolution"]["current"]
    elif "currentBullet" in incoming:
        updated["resumeEvolution"] = {**(updated.get("resumeEvolution") or {}), "current": incoming["currentBullet"]}
    if previous:
        old_bullet = (previous.get("resumeEvolution") or {}).get("current", previous.get("currentBullet"))
        new_bullet = (updated.get("resumeEvolution") or {}).get("current", updated.get("currentBullet"))
        if old_bullet != new_bullet:
            updated["resumeApproved"] = False  # Approval belongs to the reviewed wording.
    if previous:
        snapshot = {k: v for k, v in previous.items() if k != "revisionHistory"}
        updated["revisionHistory"] = [*(previous.get("revisionHistory") or []), snapshot]
    saved = upsert_entity(db, "accomplishment", updated)
    return {"success": True, "accomplishment": saved}


@router.post("/accomplishments/{accomplishment_id}/answer-question")
async def answer_question_route(
    accomplishment_id: str,
    payload: AnswerQuestionPayload,
    db: Session = Depends(db_session)
) -> dict[str, Any]:
    acc = get_entity(db, "accomplishment", accomplishment_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Accomplishment not found")

    questions = acc.get("missingQuestions", [])
    question_text = ""
    for q in questions:
        if q.get("id") == payload.questionId:
            q["answer"] = payload.answer
            question_text = q.get("question", "")
            break

    description_addon = f"\n\nQuestion: {question_text}\nAnswer: {payload.answer}"

    raw_desc = (
        acc.get("problemContext", {}).get("what", "") + "\n" +
        acc.get("roleDetails", {}).get("responsibility", "")
    )
    new_desc = raw_desc + description_addon

    result = await analyze_accomplishment(new_desc, acc)
    saved = upsert_entity(db, "accomplishment", result)
    return {"success": True, "accomplishment": saved}


@router.post("/accomplishments/ai-generate")
async def ai_generate_accomplishment_route(payload: AiGeneratePayload) -> dict[str, Any]:
    result = await analyze_accomplishment(payload.description, payload.currentData)
    return {"success": True, "accomplishment": result}


@router.delete("/accomplishments/{accomplishment_id}")
def delete_accomplishment_route(accomplishment_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    deleted = delete_entity(db, "accomplishment", accomplishment_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Accomplishment not found")
    return {"success": True}


# ── /resume-intelligence/* (scan, match, knowledge graph, Qwen) ────────────────
router.include_router(resume_intelligence_router)
