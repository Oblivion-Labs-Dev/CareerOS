"""Resume intelligence API — scan, match, knowledge graph, Qwen recommendations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.store import get_kv, session_scope
from app.services.application_assistant.persistence import get_settings
from app.services.application_assistant.llm_client import create_llm_client
from app.services.resume_intelligence.graph_builder import build_knowledge_graph
from app.services.resume_intelligence.match_engine import match_corpus_to_job
from app.services.resume_intelligence.persistence import (
    delete_person,
    get_person,
    get_scan,
    list_matches,
    list_people,
    list_scans,
    save_match,
    save_person,
)
from app.services.resume_intelligence.qwen_services import (
    enrich_ats_keywords_with_qwen,
    generate_match_recommendations,
)
from app.services.resume_intelligence.scanner import (
    commit_scan_accomplishments,
    load_accomplishments_for_person,
    run_resume_scan,
)

router = APIRouter(prefix="/resume-intelligence", tags=["resume-intelligence"])


def db_session():
    with session_scope() as db:
        yield db


class PersonPayload(BaseModel):
    fullName: str = ""
    email: str = ""
    notes: str = ""


class ScanPayload(BaseModel):
    personId: str = ""
    personName: str = ""
    text: str = ""
    base64: str = ""
    mimeType: str = ""
    filename: str = ""
    useQwen: bool = True


class CommitScanPayload(BaseModel):
    candidateIds: list[str] = Field(default_factory=list)


class MatchPayload(BaseModel):
    jobDescription: str
    jobTitle: str = ""
    personId: str = ""
    resumeText: str = ""
    useQwen: bool = True
    includeRecommendations: bool = True


@router.get("/qwen/status")
async def qwen_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    settings = get_settings(db)
    client = create_llm_client(settings)
    test = await client.test_connection() if client.enabled else {"success": False, "error": "LLM disabled"}
    return {
        "success": True,
        "enabled": client.enabled,
        "model": client.model,
        "connection": test,
    }


@router.get("/people")
def get_people(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "people": list_people(db)}


@router.post("/people")
def create_person(payload: PersonPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    if not payload.fullName.strip():
        raise HTTPException(status_code=422, detail="fullName is required")
    saved = save_person(db, payload.model_dump())
    return {"success": True, "person": saved}


@router.delete("/people/{person_id}")
def remove_person(person_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    if not delete_person(db, person_id):
        raise HTTPException(status_code=404, detail="Person not found")
    return {"success": True}


@router.get("/scans")
def get_scans(personId: str = "", db: Session = Depends(db_session)) -> dict[str, Any]:
    return {
        "success": True,
        "scans": list_scans(db, person_id=personId or None),
    }


@router.get("/scans/{scan_id}")
def get_scan_route(scan_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    scan = get_scan(db, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return {"success": True, "scan": scan}


@router.post("/scan")
async def scan_resume(payload: ScanPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    person_id = payload.personId.strip()
    if not person_id:
        if not payload.personName.strip():
            raise HTTPException(status_code=422, detail="personId or personName is required")
        person = save_person(db, {"fullName": payload.personName.strip()})
        person_id = person["id"]
    elif not get_person(db, person_id):
        raise HTTPException(status_code=404, detail="Person not found")

    if not payload.text.strip() and not payload.base64.strip():
        raise HTTPException(status_code=422, detail="Provide resume text or base64 file data")

    person = get_person(db, person_id) or {}
    try:
        scan = await run_resume_scan(
            db,
            person_id=person_id,
            text=payload.text,
            base64_data=payload.base64,
            mime_type=payload.mimeType,
            filename=payload.filename,
            use_qwen=payload.useQwen,
            person_name=person.get("fullName") or payload.personName,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"success": True, "scan": scan, "personId": person_id}


@router.post("/scans/{scan_id}/commit")
def commit_scan(scan_id: str, payload: CommitScanPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    scan = get_scan(db, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    saved = commit_scan_accomplishments(db, scan, candidate_ids=payload.candidateIds or None)
    return {"success": True, "accomplishments": saved, "count": len(saved)}


@router.post("/match")
async def match_job_route(payload: MatchPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    if not payload.jobDescription.strip():
        raise HTTPException(status_code=422, detail="jobDescription is required")

    accomplishments = load_accomplishments_for_person(db, payload.personId or None)
    profile = get_kv(db, "profile") or {}

    match = match_corpus_to_job(
        accomplishments,
        payload.jobDescription,
        job_title=payload.jobTitle,
        profile=profile,
        resume_text=payload.resumeText,
    )

    qwen_ats: dict[str, Any] | None = None
    if payload.useQwen:
        resume_summary = payload.resumeText or " ".join(
            (a.get("currentBullet") or "")[:120] for a in accomplishments[:8]
        )
        qwen_ats_result = await enrich_ats_keywords_with_qwen(
            db,
            payload.jobDescription,
            payload.jobTitle,
            resume_summary,
        )
        if qwen_ats_result.get("success"):
            qwen_ats = qwen_ats_result.get("data")

    recommendations: dict[str, Any] | None = None
    if payload.includeRecommendations and payload.useQwen:
        rec_result = await generate_match_recommendations(
            db,
            job_title=payload.jobTitle,
            job_description=payload.jobDescription,
            match_result=match,
            accomplishments=accomplishments,
        )
        if rec_result.get("success"):
            recommendations = rec_result.get("data")

    saved = save_match(db, {
        "personId": payload.personId,
        "jobTitle": payload.jobTitle,
        "jobDescriptionPreview": payload.jobDescription[:500],
        "match": match,
        "qwenAts": qwen_ats,
        "recommendations": recommendations,
    })

    return {
        "success": True,
        "matchId": saved["id"],
        "match": match,
        "qwenAts": qwen_ats,
        "recommendations": recommendations,
    }


@router.get("/matches")
def get_matches(personId: str = "", db: Session = Depends(db_session)) -> dict[str, Any]:
    return {
        "success": True,
        "matches": list_matches(db, person_id=personId or None),
    }


@router.get("/graph")
def get_graph(personId: str = "", db: Session = Depends(db_session)) -> dict[str, Any]:
    accomplishments = load_accomplishments_for_person(db, personId or None)
    graph = build_knowledge_graph(accomplishments)
    return {"success": True, "graph": graph, "accomplishmentCount": len(accomplishments)}


@router.post("/recommendations")
async def recommendations_only(payload: MatchPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    if not payload.jobDescription.strip():
        raise HTTPException(status_code=422, detail="jobDescription is required")
    accomplishments = load_accomplishments_for_person(db, payload.personId or None)
    match = match_corpus_to_job(
        accomplishments,
        payload.jobDescription,
        job_title=payload.jobTitle,
        profile=get_kv(db, "profile") or {},
        resume_text=payload.resumeText,
    )
    rec_result = await generate_match_recommendations(
        db,
        job_title=payload.jobTitle,
        job_description=payload.jobDescription,
        match_result=match,
        accomplishments=accomplishments,
    )
    if not rec_result.get("success"):
        raise HTTPException(status_code=502, detail=rec_result.get("error") or "Qwen recommendations failed")
    return {"success": True, "match": match, "recommendations": rec_result.get("data")}
