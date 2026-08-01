"""Job search workflow routes (fit evaluation, rank, outcomes, analytics report)."""

from __future__ import annotations

from typing import Any, Generator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.store import (
    enrich_application_record,
    get_kv,
    list_entities,
    new_id,
    now_iso,
    session_scope,
    upsert_entity,
)
from app.services.job_discover import store as job_discover_store
from app.services.job_search.cover_letter_pipeline import generate_cover_letter_with_review
from app.services.job_search.html_report import build_analytics_summary, render_html_report
from app.services.job_search.job_evaluation import evaluate_job_fit, rank_jobs
from app.services.job_search.outcome_archive import list_outcome_archives, write_outcome_archive
from app.services.market_trends import market_trends_summary
from app.services.application_assistant.greenhouse_schema import fetch_greenhouse_schema, parse_greenhouse_url

router = APIRouter(tags=["job-search"])


def db_session() -> Generator[Session, None, None]:
    with session_scope() as db:
        yield db


class JobEvaluatePayload(BaseModel):
    job: dict[str, Any]


class JobRankPayload(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)


class OutcomeRecordPayload(BaseModel):
    status: str
    notes: str = ""
    interviewStages: list[dict[str, Any]] = Field(default_factory=list)
    jobPosting: str | None = None
    coverLetter: str | None = None
    dateResolved: str | None = None
    patchApplicationStatus: bool = True


class CoverLetterEnhancedPayload(BaseModel):
    jobId: str | None = None
    companyName: str | None = None
    roleTitle: str | None = None
    jobDescription: str | None = None
    tone: str | None = "professional"
    useLlm: bool = True


def _profile_for_evaluation(db: Session) -> dict[str, Any]:
    return get_kv(db, "profile") or {}


def _applied_dedupe_keys(applications: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for app in applications:
        company = str(app.get("companyName") or app.get("company") or "").strip().lower()
        role = str(app.get("roleTitle") or app.get("role") or "").strip().lower()
        if company and role:
            keys.add(f"{company}|{role}")
    return keys


@router.post("/jobs/evaluate-fit")
def evaluate_fit(payload: JobEvaluatePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    evaluation = evaluate_job_fit(payload.job, _profile_for_evaluation(db))
    return {"success": True, "evaluation": evaluation}


@router.post("/jobs/rank")
def rank_discovered_jobs(payload: JobRankPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    profile = _profile_for_evaluation(db)
    applications = list_entities(db, "application")
    exclude = _applied_dedupe_keys(applications)

    snapshot = job_discover_store.get_snapshot(db)
    jobs = snapshot.get("jobs") or []
    ranked = rank_jobs(jobs, profile, exclude_applied=exclude)[: payload.limit]

    return {
        "success": True,
        "totalEvaluated": len(jobs),
        "shortlistCount": len(ranked),
        "jobs": ranked,
    }


@router.post("/cover-letter/generate-reviewed")
async def generate_reviewed_cover_letter(
    payload: CoverLetterEnhancedPayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    profile = _profile_for_evaluation(db)
    company = payload.companyName or "the company"
    role = payload.roleTitle or profile.get("targetRole") or "the role"

    result = await generate_cover_letter_with_review(
        profile,
        company=company,
        role=role,
        job_description=payload.jobDescription or "",
        tone=payload.tone or "professional",
        use_llm=payload.useLlm,
    )

    letter = {
        "id": new_id("cl_"),
        "jobId": payload.jobId,
        "title": result["title"],
        "content": result["content"],
        "tone": payload.tone,
        "pipelineMode": result["pipelineMode"],
        "reviewerNotes": result["reviewerNotes"],
        "styleIssues": result["styleIssues"],
        "createdAt": now_iso(),
    }
    upsert_entity(db, "cover_letter", letter)
    return {"success": True, "coverLetter": letter}


@router.post("/applications/{application_id}/outcome")
def record_application_outcome(
    application_id: str,
    payload: OutcomeRecordPayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    applications = list_entities(db, "application")
    application = next((app for app in applications if app.get("id") == application_id), None)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    archive = write_outcome_archive(
        application,
        status=payload.status,
        notes=payload.notes,
        interview_stages=payload.interviewStages,
        job_posting=payload.jobPosting,
        cover_letter=payload.coverLetter,
        date_resolved=payload.dateResolved,
    )

    updated = dict(application)
    if payload.notes:
        prior = str(updated.get("notes") or "").strip()
        stamp = now_iso()[:10]
        note_line = f"[{stamp}] {payload.notes.strip()}"
        updated["notes"] = f"{prior}\n{note_line}".strip() if prior else note_line
    updated["outcomeStatus"] = payload.status
    updated["outcomeArchivePath"] = archive["archivePath"]
    updated["updatedAt"] = now_iso()

    if payload.patchApplicationStatus:
        status_map = {
            "hired": "hired",
            "rejected": "rejected",
            "no_response": "no_response",
            "offer_declined": "offer_declined",
            "interview_only": "interviewing",
            "in_progress": updated.get("status") or "submitted",
        }
        mapped = status_map.get(payload.status)
        if mapped:
            updated["status"] = mapped

    upsert_entity(db, "application", updated)

    return {"success": True, "application": enrich_application_record(updated), "archive": archive}


@router.get("/analytics/summary")
def analytics_summary(db: Session = Depends(db_session)) -> dict[str, Any]:
    applications = [enrich_application_record(app) for app in list_entities(db, "application")]
    summary = build_analytics_summary(applications)
    archives = list_outcome_archives()
    market = market_trends_summary(country="US")
    return {"success": True, "summary": summary, "outcomeArchives": archives, "marketTrends": market}


@router.get("/analytics/market-trends")
def analytics_market_trends(country: str = "US") -> dict[str, Any]:
    return {"success": True, "marketTrends": market_trends_summary(country=country)}


@router.get("/greenhouse/schema")
async def greenhouse_question_schema(url: str = Query(..., min_length=8)) -> dict[str, Any]:
    if not parse_greenhouse_url(url):
        raise HTTPException(status_code=400, detail="Not a Greenhouse job URL")
    schema = await fetch_greenhouse_schema(url)
    if not schema:
        raise HTTPException(status_code=404, detail="Could not load Greenhouse question schema")
    fields = {key: value for key, value in schema.items() if not key.startswith("label:")}
    return {"success": True, "url": url, "fieldCount": len(fields), "fields": fields}


@router.get("/analytics/report", response_class=HTMLResponse)
def analytics_html_report(db: Session = Depends(db_session)) -> HTMLResponse:
    applications = [enrich_application_record(app) for app in list_entities(db, "application")]
    html = render_html_report(applications)
    return HTMLResponse(html)
