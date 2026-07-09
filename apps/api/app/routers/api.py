import json
from pathlib import Path
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
from app.services.gmail_imap import GmailImapClient
from app.services.gmail_sender import SendEmailPayload, build_gmail_sender
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


def require_protected_action_auth(request: Request) -> None:
    """Guard sensitive write actions when not in local dev mode."""
    if settings.career_os_dev_mode:
        return
    if not settings.career_os_api_key:
        raise HTTPException(status_code=503, detail="Action disabled until CAREER_OS_API_KEY is set")
    provided = request.headers.get("x-career-os-api-key", "")
    if provided != settings.career_os_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


def require_gmail_configured() -> tuple[str, str]:
    if not settings.gmail_user or not settings.gmail_app_password:
        raise HTTPException(
            status_code=503,
            detail="Gmail is not configured. Set GMAIL_USER and GMAIL_APP_PASSWORD in apps/api/.env",
        )
    return settings.gmail_user, settings.gmail_app_password


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


class ReferralAskMessagePayload(BaseModel):
    message: str


DEFAULT_REFERRAL_ASK_MESSAGE = """I hope you're doing well! I came across a job that aligns closely with my background and was wondering if you'd be open to referring me. I have 7+ years of experience at Microsoft and Amazon building distributed systems, AI infrastructure, and cloud-native platforms, and I've recently been focused on agentic AI and developer tooling.

I believe my experience is a strong match for the role. If you're comfortable referring me, I'd really appreciate it. I've attached the job link and my resume for context. Thanks for taking the time to consider my request!"""


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


@router.get("/referrals/ask-message")
def get_referral_ask_message(db: Session = Depends(db_session)) -> dict[str, Any]:
    stored = get_kv(db, "referral_ask_message")
    message = stored if isinstance(stored, str) and stored.strip() else DEFAULT_REFERRAL_ASK_MESSAGE
    return {"message": message}


@router.put("/referrals/ask-message")
def save_referral_ask_message(
    payload: ReferralAskMessagePayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    set_kv(db, "referral_ask_message", message)
    return {"success": True, "message": message}


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


# Gmail / recruiter email (migrated from Arsenal scripts/email)
@router.get("/email/verify")
def verify_gmail_connection() -> dict[str, Any]:
    user, app_password = require_gmail_configured()
    sender = build_gmail_sender(user, app_password)
    return {"success": sender.verify_connection(), "user": user}


@router.post("/email/send")
def send_email(payload: SendEmailPayload, request: Request) -> dict[str, Any]:
    require_protected_action_auth(request)
    user, app_password = require_gmail_configured()
    sender = build_gmail_sender(user, app_password)
    try:
        result = sender.send(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"success": True, **result}


@router.get("/email/recruiter-threads")
def list_recruiter_threads(limit: int = Query(default=10, ge=1, le=150)) -> dict[str, Any]:
    user, app_password = require_gmail_configured()
    client = GmailImapClient(user, app_password)
    threads = client.fetch_threads(limit=limit)
    return {"success": True, "threads": threads, "count": len(threads)}


@router.get("/email/recruiter-conversations")
def get_cached_recruiter_conversations() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "data" / "recruiter_conversations.json"
    if not path.exists():
        return {"success": True, "conversations": [], "count": 0, "source": "cache-missing"}
    conversations = json.loads(path.read_text(encoding="utf-8"))
    return {"success": True, "conversations": conversations, "count": len(conversations), "source": str(path)}


def _load_bounced_email_set() -> tuple[set[str], int]:
    path = Path(__file__).resolve().parents[2] / "data" / "bounced_recruiter_emails.json"
    if not path.exists():
        return set(), 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    invalid = {str(item.get("email", "")).lower() for item in payload.get("invalidEmails", []) if item.get("email")}
    return invalid, int(payload.get("bounceMessages", 0) or 0)


def _compute_delivery_stats(results: list[dict[str, Any]], bounced: set[str]) -> dict[str, int]:
    sent = [result for result in results if result.get("status") == "sent"]
    failed = [result for result in results if result.get("status") == "failed"]
    bounced_sent = [result for result in sent if str(result.get("email", "")).lower() in bounced]
    invalid_in_list = {
        str(result.get("email", "")).lower()
        for result in results
        if str(result.get("email", "")).lower() in bounced
    }
    return {
        "delivered": len(sent) - len(bounced_sent),
        "bounced": len(bounced_sent),
        "undelivered": len(bounced_sent) + len(failed),
        "invalid": len(invalid_in_list),
        "sendFailed": len(failed),
        "pending": len([result for result in results if result.get("status") in {"pending", "retrying", "paused"}]),
    }


def _enrich_outreach_result(result: dict[str, Any], bounced: set[str]) -> dict[str, Any]:
    enriched = dict(result)
    email = str(enriched.get("email", "")).lower()
    status = enriched.get("status")
    if status == "sent" and email in bounced:
        enriched["deliveryStatus"] = "bounced"
    elif status == "sent":
        enriched["deliveryStatus"] = "delivered"
    elif status == "failed":
        enriched["deliveryStatus"] = "failed"
    else:
        enriched["deliveryStatus"] = "pending"
    return enriched


def _prepare_outreach_campaign(
    campaign: dict[str, Any],
    bounced: set[str],
    bounce_messages: int,
    recent_limit: int,
) -> dict[str, Any]:
    prepared = dict(campaign)
    results = list(prepared.get("results") or [])
    prepared["deliveryStats"] = {
        **_compute_delivery_stats(results, bounced),
        "bounceMessages": bounce_messages,
    }
    recent = sorted(
        results,
        key=lambda result: str(result.get("sentAt") or ""),
        reverse=True,
    )[:recent_limit]
    prepared["results"] = [_enrich_outreach_result(result, bounced) for result in recent]
    prepared["recentLimit"] = recent_limit
    prepared["resultsTotal"] = len(results)
    return prepared


@router.get("/email/outreach-campaigns")
def get_recruiter_outreach_campaigns(
    limit: int = Query(default=20, ge=1, le=100),
    recent_limit: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "data" / "recruiter_outreach_campaigns.json"
    if not path.exists():
        return {"success": True, "campaigns": [], "count": 0, "source": "cache-missing"}
    raw_campaigns = json.loads(path.read_text(encoding="utf-8"))
    bounced, bounce_messages = _load_bounced_email_set()
    full_campaigns = raw_campaigns[:limit]
    campaigns = [
        _prepare_outreach_campaign(campaign, bounced, bounce_messages, recent_limit)
        for campaign in full_campaigns
    ]
    all_full_results = [result for campaign in full_campaigns for result in (campaign.get("results") or [])]
    aggregate_stats = {
        **_compute_delivery_stats(all_full_results, bounced),
        "bounceMessages": bounce_messages,
    }
    return {
        "success": True,
        "campaigns": campaigns,
        "count": len(campaigns),
        "aggregateDeliveryStats": aggregate_stats,
        "source": str(path),
    }


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
