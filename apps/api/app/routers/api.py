from typing import Any, Generator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db.store import (
    EntityStore,
    get_kv,
    import_legacy_db,
    legacy_db_snapshot,
    list_entities,
    new_id,
    now_iso,
    patch_entity,
    session_scope,
    set_kv,
    tracker_summary,
    upsert_entity,
)
from app.services.extension_packager import build_extension_zip, extension_info
from app.services.log_store import append_client_log, clear_client_logs, read_client_logs
from app.services.resume_parser import parse_resume_into_profile

router = APIRouter()


def require_legacy_sync_auth(request: Request) -> None:
    """Guard full DB overwrite when not in local dev mode."""
    if settings.career_os_dev_mode:
        return
    if not settings.career_os_api_key:
        raise HTTPException(status_code=503, detail="Legacy sync is disabled until CAREER_OS_API_KEY is set")
    provided = request.headers.get("x-career-os-api-key", "")
    if provided != settings.career_os_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


def db_session() -> Generator[Session, None, None]:
    with session_scope() as db:
        yield db


class ProfilePayload(BaseModel):
    profile: dict[str, Any]


class JobExtractPayload(BaseModel):
    url: str
    html: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None
    platform: str | None = None


class JobSavePayload(BaseModel):
    job: dict[str, Any]


class ApplicationPayload(BaseModel):
    application: dict[str, Any]


class ApplicationPatchPayload(BaseModel):
    patch: dict[str, Any]


class FieldMappingPayload(BaseModel):
    mapping: dict[str, Any]


class ResumePayload(BaseModel):
    resume: dict[str, Any]


class CoverLetterGeneratePayload(BaseModel):
    jobId: str | None = None
    companyName: str | None = None
    roleTitle: str | None = None
    jobDescription: str | None = None
    tone: str | None = "professional"


class QuestionAnswerPayload(BaseModel):
    question: str
    context: dict[str, Any] | None = None


class AnalyticsEventPayload(BaseModel):
    type: str
    module: str | None = None
    message: str
    metadata: dict[str, Any] | None = None


class ReferralPayload(BaseModel):
    referral: dict[str, Any]


class ReferralPatchPayload(BaseModel):
    patch: dict[str, Any]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "career-os-api"}


@router.get("/profile")
def get_profile(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"profile": get_kv(db, "profile")}


@router.post("/profile")
def upsert_profile(payload: ProfilePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    set_kv(db, "profile", payload.profile)
    return {"success": True, "profile": payload.profile}


@router.post("/jobs/extract")
def extract_job(payload: JobExtractPayload) -> dict[str, Any]:
    job = {
        "id": new_id("job_"),
        "companyName": payload.company or "Unknown company",
        "title": payload.title or "Unknown role",
        "location": payload.location or "",
        "description": payload.description or "",
        "url": payload.url,
        "platform": payload.platform or "",
        "extractedAt": now_iso(),
    }
    return {"success": True, "job": job}


@router.post("/jobs/save")
def save_job(payload: JobSavePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    saved = upsert_entity(db, "job", {**payload.job, "savedAt": payload.job.get("savedAt") or now_iso()})
    return {"success": True, "job": saved}


@router.get("/jobs")
def list_jobs(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"jobs": list_entities(db, "job")}


@router.post("/applications")
def create_application(payload: ApplicationPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    saved = upsert_entity(db, "application", payload.application)
    return {"success": True, "application": saved}


@router.get("/applications")
def list_applications(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"applications": list_entities(db, "application")}


@router.get("/tracker/summary")
def get_tracker_summary(db: Session = Depends(db_session)) -> dict[str, Any]:
    return tracker_summary(db)


@router.patch("/applications/{application_id}")
def update_application(
    application_id: str,
    payload: ApplicationPatchPayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    updated = patch_entity(db, "application", application_id, payload.patch)
    if not updated:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"success": True, "application": updated}


@router.post("/autofill/map-field")
def map_field(payload: FieldMappingPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    mapping = upsert_entity(
        db,
        "field_mapping",
        {
            **payload.mapping,
            "id": payload.mapping.get("id") or new_id("map_"),
            "lastUsedAt": now_iso(),
        },
    )
    return {"success": True, "mapping": mapping}


@router.get("/autofill/mappings")
def list_mappings(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"mappings": list_entities(db, "field_mapping")}


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


@router.post("/cover-letter/generate")
def generate_cover_letter(payload: CoverLetterGeneratePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    profile = get_kv(db, "profile") or {}
    company = payload.companyName or "the company"
    role = payload.roleTitle or profile.get("targetRole") or "the role"
    name = profile.get("fullName") or "Candidate"
    content = (
        f"Dear Hiring Team at {company},\n\n"
        f"I am excited to apply for the {role} position. With {profile.get('yearsExperience', 'several')} years "
        f"of experience as a {profile.get('currentTitle', 'professional')}, I believe my background aligns well "
        f"with your needs.\n\n"
        f"{payload.jobDescription[:400] + '...' if payload.jobDescription else 'I am motivated by impactful work and collaborative teams.'}\n\n"
        f"Thank you for your consideration.\n\nSincerely,\n{name}"
    )
    letter = {
        "id": new_id("cl_"),
        "jobId": payload.jobId,
        "title": f"Cover letter — {role} at {company}",
        "content": content,
        "tone": payload.tone,
        "createdAt": now_iso(),
    }
    upsert_entity(db, "cover_letter", letter)
    return {"success": True, "coverLetter": letter}


@router.post("/questions/answer")
def answer_question(payload: QuestionAnswerPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    learned = list_entities(db, "learned_answer")
    normalized = payload.question.strip().lower()
    for item in learned:
        if item.get("question", "").strip().lower() == normalized:
            return {"success": True, "answer": item.get("answer"), "source": "learned"}
    profile = get_kv(db, "profile") or {}
    fallback = (
        f"Based on my experience as {profile.get('currentTitle', 'a professional')}, "
        f"I would approach this thoughtfully and align with {profile.get('targetRole', 'the role')} expectations."
    )
    return {"success": True, "answer": fallback, "source": "generated"}


@router.post("/analytics/event")
def track_event(payload: AnalyticsEventPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    event = upsert_entity(
        db,
        "career_event",
        {
            "id": new_id("evt_"),
            "type": payload.type,
            "module": payload.module,
            "message": payload.message,
            "metadata": payload.metadata or {},
            "createdAt": now_iso(),
        },
    )
    return {"success": True, "event": event}


@router.get("/referrals")
def list_referrals(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"referrals": list_entities(db, "referral")}


@router.post("/referrals")
def create_referral(payload: ReferralPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    saved = upsert_entity(
        db,
        "referral",
        {
            **payload.referral,
            "id": payload.referral.get("id") or new_id("ref_"),
            "status": payload.referral.get("status") or "active",
        },
    )
    return {"success": True, "referral": saved}


@router.patch("/referrals/{referral_id}")
def update_referral(
    referral_id: str,
    payload: ReferralPatchPayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    updated = patch_entity(db, "referral", referral_id, payload.patch)
    if not updated:
        raise HTTPException(status_code=404, detail="Referral contact not found")
    return {"success": True, "referral": updated}


@router.delete("/referrals/{referral_id}")
def delete_referral(referral_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    row = (
        db.query(EntityStore)
        .filter(EntityStore.entity_type == "referral", EntityStore.id == referral_id)
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Referral contact not found")
    db.delete(row)
    return {"success": True}


# Legacy extension compatibility
@router.get("/api/db")
def legacy_get_db(db: Session = Depends(db_session)) -> dict[str, Any]:
    return legacy_db_snapshot(db)


@router.post("/api/db")
def legacy_post_db(
    payload: dict[str, Any],
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    require_legacy_sync_auth(request)
    import_legacy_db(db, payload)
    return {"success": True}


class ParseResumePayload(BaseModel):
    force: bool = False


@router.post("/api/parse-resume")
def legacy_parse_resume(payload: ParseResumePayload | None = None, db: Session = Depends(db_session)) -> dict[str, Any]:
    profile = get_kv(db, "profile") or {}
    documents = get_kv(db, "documents") or {}
    try:
        result = parse_resume_into_profile(profile, documents, force=bool(payload and payload.force))
        set_kv(db, "profile", result["profile"])
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/logs")
def legacy_get_logs(limit: int = 100) -> dict[str, Any]:
    logs = read_client_logs(limit)
    return {"success": True, "logs": logs}


@router.post("/api/logs")
def legacy_post_log(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("message"):
        raise HTTPException(status_code=400, detail="message is required")
    append_client_log(payload)
    return {"success": True}


@router.delete("/api/logs")
def legacy_delete_logs() -> dict[str, Any]:
    clear_client_logs()
    return {"success": True}


@router.get("/extension/info")
def get_extension_info() -> dict[str, Any]:
    return extension_info()


@router.get("/extension/download")
def download_extension(browser: str = Query(default="chrome")) -> Response:
    normalized = browser.lower().strip()
    engine = "firefox" if normalized == "firefox" else "chromium"
    try:
        payload, filename = build_extension_zip(engine)  # type: ignore[arg-type]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
