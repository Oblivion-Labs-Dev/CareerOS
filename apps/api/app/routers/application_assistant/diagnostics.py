"""Application Assistant API routes — diagnostics domain."""

from ._common import *  # noqa: F401,F403

router = APIRouter(prefix="/application-assistant", tags=["application-assistant"])


# ── Diagnostics ───────────────────────────────────────────────────────────────

@router.get("/applications/{app_id}/diagnostics")
def export_diagnostics(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.log_redaction import redact_dict

    draft = get_application_draft(db, app_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Application not found")

    browser_run = get_active_browser_run_for_app(db, app_id)
    sanitized_fields = []
    for field in draft.get("fields", []):
        sanitized_fields.append({
            "label": field.get("label"),
            "normalizedKey": field.get("normalizedKey"),
            "classification": field.get("classification"),
            "filled": field.get("filled"),
            "required": field.get("required"),
            "sensitivityCategory": field.get("sensitivityCategory"),
        })

    return {
        "success": True,
        "bundle": redact_dict({
            "applicationId": app_id,
            "company": draft.get("companyName"),
            "role": draft.get("roleTitle"),
            "provider": draft.get("provider"),
            "status": draft.get("status"),
            "progress": draft.get("progress"),
            "fields": sanitized_fields,
            "errors": draft.get("errors", []),
            "skipped": draft.get("skipped", []),
            "prepLog": draft.get("prepLog"),
            "stoppedReason": draft.get("stoppedReason", ""),
            "browserRun": {
                "id": browser_run.get("id") if browser_run else None,
                "status": browser_run.get("status") if browser_run else None,
                "tracePath": browser_run.get("tracePath") if browser_run else None,
            },
            "screenshotCount": len(draft.get("screenshots", [])),
        }),
    }


@router.post("/generate-answer")
async def generate_answer_route(
    payload: GenerateAnswerPayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Generate answer for a freeform screening/textarea question using Ollama Qwen + user profile."""
    from app.services.application_assistant.llm_answer_generator import generate_theory_answer

    profile = get_kv(db, "profile") or {}
    docs = get_kv(db, "documents") or {}
    default_resume = docs.get("defaultResume") or {}
    resume_text = default_resume.get("text") or default_resume.get("content") or profile.get("resumeText") or ""
    settings = get_settings(db)

    result = await generate_theory_answer(
        payload.question,
        company=payload.company,
        role=payload.role,
        job_description=payload.jobDescription,
        profile=profile,
        resume_text=resume_text,
        settings=settings,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Answer generation failed"))
    return result


