"""Career OS resume compiler: job description in, evidence-backed one-page resume out."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.services.career_compiler.models import Bullet, ResumePlan

router = APIRouter(prefix="/career", tags=["career-compiler"])


class AnalyzePayload(BaseModel):
    jobDescription: str = Field(default="", max_length=40000)
    url: str = Field(default="", max_length=2000)
    title: str = Field(default="", max_length=200)
    company: str = Field(default="", max_length=200)
    refresh: bool = False
    jobId: str = Field(default="", max_length=200)


def _discover_job(job_id: str) -> dict:
    from app.db.store import session_scope
    from app.services.job_discover import store as job_discover
    with session_scope() as db:
        job = job_discover.get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="That job is no longer in Discover.")
    return job


class GeneratePayload(BaseModel):
    jd_id: str = Field(pattern="^[0-9a-f]{16}$")
    plan: ResumePlan
    bullets: list[Bullet] = Field(default_factory=list)
    regenerate: list[str] | None = None


@router.post("/analyze")
async def analyze_job(payload: AnalyzePayload):
    from app.services.career_compiler.pipeline import analyze
    if payload.jobId:
        job = await run_in_threadpool(_discover_job, payload.jobId)
        payload = payload.model_copy(update={
            "jobDescription": payload.jobDescription or str(job.get("description") or ""),
            "url": payload.url or str(job.get("url") or ""), "title": payload.title or str(job.get("title") or ""),
            "company": payload.company or str(job.get("companyName") or "")})
    if not payload.jobDescription.strip() and not payload.url.strip():
        raise HTTPException(status_code=422, detail="Paste a job description or a job URL.")
    try:
        return await run_in_threadpool(analyze, text=payload.jobDescription, url=payload.url.strip(),
                                       title=payload.title, company=payload.company, refresh=payload.refresh)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/jd/{jd_id}")
async def get_jd(jd_id: str):
    from app.services.career_compiler.jobs import load_jd
    try:
        return load_jd(jd_id).model_dump()
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/generate")
async def generate_resume(payload: GeneratePayload):
    from app.services.career_compiler.pipeline import CompilerUnavailable, generate
    from app.services.career_compiler.word import ConverterUnavailable
    try:
        return await run_in_threadpool(generate, jd_id=payload.jd_id, plan=payload.plan, bullets=payload.bullets,
                                       regenerate=payload.regenerate)
    except (CompilerUnavailable, ConverterUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


MEDIA = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "pdf": "application/pdf"}


@router.post("/export")
async def export_resume(document: dict, format: Literal["docx", "pdf"] = "docx"):
    from app.services.career_compiler.export import export
    from app.services.career_compiler.versions import recruiter_filename
    from app.services.career_compiler.word import ConverterUnavailable
    if document.get("method") != "career-compiler-v1":
        raise HTTPException(status_code=422, detail="Not a Career OS compiler document.")
    try:
        data = await run_in_threadpool(export, document, format)
    except ConverterUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(data, media_type=MEDIA[format],
                    headers={"Content-Disposition": f'attachment; filename="{recruiter_filename(format)}"'})


@router.post("/feedback")
async def record_feedback(payload: dict):
    from app.services.career_compiler.feedback import FeedbackRecord, record
    try:
        item = FeedbackRecord.model_validate({k: v for k, v in payload.items() if k not in ("id", "created_at")})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return record(item).model_dump()


@router.get("/feedback")
async def list_feedback(jd_id: str | None = None):
    from app.services.career_compiler.feedback import excluded_evidence, load, stats
    items = load(jd_id)
    return {"items": [i.model_dump() for i in items[-200:]], "stats": stats(jd_id),
            "excluded_evidence": sorted(excluded_evidence(jd_id)) if jd_id else []}


@router.get("/feedback/pairs")
async def feedback_pairs():
    from app.services.career_compiler.feedback import preference_pairs
    return {"pairs": preference_pairs()}


def _version_or_404(resume_id: str):
    from app.services.career_compiler.versions import load_version
    try:
        return load_version(resume_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/resumes")
async def list_resumes(jd_id: str | None = None):
    from app.services.career_compiler.versions import blocking_reasons, list_versions, version_label
    versions = list_versions(jd_id)
    return {"versions": [{**v.model_dump(exclude={"requirement_mappings"}), "label": version_label(v, versions),
                          "blocking": blocking_reasons(v)} for v in versions]}


@router.get("/resumes/{resume_id}")
async def get_resume(resume_id: str):
    from app.services.career_compiler.versions import CONFOUNDERS, blocking_reasons, outcomes
    version = _version_or_404(resume_id)
    return {**version.model_dump(), "blocking": blocking_reasons(version), "outcomes": outcomes(resume_id),
            "outcome_confounders": list(CONFOUNDERS)}


@router.get("/resumes/{resume_id}/download")
async def download_resume(resume_id: str, format: Literal["docx", "pdf"] = "pdf"):
    from app.services.career_compiler.versions import recruiter_artifact, recruiter_filename
    version = _version_or_404(resume_id)
    try:
        data = recruiter_artifact(resume_id, format)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(data, media_type=MEDIA[format], headers={
        "Content-Disposition": f'attachment; filename="{recruiter_filename(format)}"',
        "X-Resume-Version": resume_id, "X-Content-SHA256": version.docx_sha256 if format == "docx" else version.pdf_sha256 or ""})


class ApprovePayload(BaseModel):
    locks: list[str] = Field(default_factory=list)


@router.post("/resumes/{resume_id}/approve")
async def approve_resume(resume_id: str, payload: ApprovePayload):
    from app.services.career_compiler.versions import approve
    _version_or_404(resume_id)
    try:
        return approve(resume_id, payload.locks).model_dump()
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class ApplyPayload(BaseModel):
    applicationUrl: str = Field(default="", max_length=2000)
    company: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=200)
    locks: list[str] = Field(default_factory=list)


@router.post("/resumes/{resume_id}/apply")
async def apply_with_resume(resume_id: str, payload: ApplyPayload):
    """Approve (freezing the version) and queue the job for the application agent, bound to this exact PDF."""
    from app.db.store import session_scope
    from app.routers.application_assistant.autopilot import enqueue_job_for_autopilot
    from app.services.career_compiler.versions import approve, link_application
    version = _version_or_404(resume_id)
    url = payload.applicationUrl.strip() or version.job_url
    if not url:
        raise HTTPException(status_code=422, detail="Add the job's application URL to apply with this resume.")
    try:
        version = approve(resume_id, payload.locks)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    def enqueue() -> dict:
        with session_scope() as db:
            return enqueue_job_for_autopilot({"applicationUrl": url, "company": payload.company or version.job_company,
                                              "title": payload.title or version.job_title, "careerResumeId": resume_id,
                                              "tailoringMode": "off"}, db)

    result = await run_in_threadpool(enqueue)
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result.get("message") or "The application agent would not queue this job.")
    job = result.get("job") or {}
    if job.get("careerResumeId") != resume_id:
        raise HTTPException(status_code=409, detail=f"This job is already {job.get('status', 'queued')} with another resume.")
    linked = link_application(resume_id, {"autopilot_job_id": job.get("id"), "application_url": url,
                                          "deduplicated": bool(result.get("deduplicated"))})
    return {"version": linked.model_dump(), "job": {k: job.get(k) for k in ("id", "status", "company", "title", "applicationUrl")},
            "message": result.get("message") or "Queued for the application agent with this exact resume."}


class AppliedPayload(BaseModel):
    applicationUrl: str = Field(default="", max_length=2000)
    jobId: str = Field(default="", max_length=200)
    answers: dict[str, str] = Field(default_factory=dict)


@router.post("/resumes/{resume_id}/applied")
async def mark_applied(resume_id: str, payload: AppliedPayload):
    """The user submitted this approved version themselves. Snapshots the application; idempotent per URL."""
    from app.services.career_compiler.versions import record_manual_application
    version = _version_or_404(resume_id)
    url = payload.applicationUrl.strip() or version.job_url
    if not url:
        raise HTTPException(status_code=422, detail="Add the job's application URL.")
    try:
        return record_manual_application(resume_id, url, payload.jobId, payload.answers).model_dump()
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/resumes/{resume_id}/interview-prep")
async def interview_prep(resume_id: str):
    from app.services.career_compiler.versions import interview_checklist
    _version_or_404(resume_id)
    return await run_in_threadpool(interview_checklist, resume_id)


class OutcomePayload(BaseModel):
    outcome: Literal["applied", "recruiter_response", "screen", "technical_interview", "onsite", "offer", "rejected", "withdrawn"]
    note: str = Field(default="", max_length=500)
    at: str | None = None


@router.post("/resumes/{resume_id}/outcomes")
async def add_outcome(resume_id: str, payload: OutcomePayload):
    from app.services.career_compiler.versions import outcomes, record_outcome
    _version_or_404(resume_id)
    record_outcome(resume_id, payload.outcome, payload.note, payload.at)
    return {"outcomes": outcomes(resume_id)}
