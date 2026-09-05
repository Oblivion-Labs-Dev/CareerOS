"""Application Assistant API routes — qwen domain."""

from ._common import *  # noqa: F401,F403

router = APIRouter(prefix="/application-assistant", tags=["application-assistant"])


# ── Qwen agent (metrics, logs, chat) ──────────────────────────────────────────

QWEN_SYSTEM_PROMPT = """You are Qwen, the autonomous application assistant inside CareerOS.
You run application preparation in a visible browser and log every step.
The user watches your activity log — they do not drive prep manually.
When asked what went wrong, use the prep context provided and explain clearly.
If the issue is a UI or backend bug, name the layer and suggest a specific fix.
Never claim to submit applications or bypass submission guards."""


@router.post("/qwen/agent/prepare")
async def qwen_agent_prepare(payload: QwenAgentPreparePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.agent import (
        start_autonomous_prepare,
        start_autonomous_prepare_for_job,
    )

    if payload.applicationId:
        result = await start_autonomous_prepare(payload.applicationId)
    elif payload.jobId:
        result = await start_autonomous_prepare_for_job(payload.jobId)
    else:
        raise HTTPException(status_code=400, detail="Provide jobId or applicationId")

    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result.get("error", "Agent prep failed"))
    return result


@router.get("/qwen/agent/prep-queue")
def qwen_agent_prep_queue() -> dict[str, Any]:
    from app.services.application_assistant.worker import prep_queue_status

    return {"success": True, **prep_queue_status()}


@router.get("/qwen/agent/status/{app_id}")
def qwen_agent_status(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.agent import get_agent_run

    run = get_agent_run(db, app_id)
    draft = get_application_draft(db, app_id)
    return {"success": True, "run": run, "application": draft}


@router.get("/qwen/status")
async def qwen_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import update_connection_status

    settings = get_settings(db)
    llm = settings.get("llm", {})
    client = create_llm_client(settings)
    ping = await client.test_connection()
    model = llm.get("model") or (ping.get("models", [""])[0] if ping.get("models") else "")
    metrics = update_connection_status(db, connected=ping.get("success", False), model=model)
    return {
        "success": True,
        "connected": ping.get("success", False),
        "model": model,
        "baseUrl": llm.get("baseUrl", ""),
        "provider": llm.get("provider", "ollama"),
        "models": ping.get("models", []),
        "error": ping.get("error"),
        "metrics": metrics,
    }


@router.get("/qwen/metrics")
def qwen_metrics(db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import get_metrics

    settings = get_settings(db)
    return {
        "success": True,
        "metrics": get_metrics(db),
        "llm": settings.get("llm", {}),
    }


@router.get("/qwen/logs")
def qwen_logs(
    db: Session = Depends(db_session),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import (
        get_active_analyze_from_logs,
        get_active_prep_from_logs,
        get_logs,
    )

    return {
        "success": True,
        "logs": get_logs(db, limit=limit),
        "activePrep": get_active_prep_from_logs(db),
        "activeAnalyze": get_active_analyze_from_logs(db),
    }


@router.get("/qwen/live")
def qwen_live_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import (
        get_active_analyze_from_logs,
        get_active_prep_from_logs,
        get_logs,
        get_metrics,
    )
    from app.services.application_assistant.agent import get_agent_run

    active_prep = get_active_prep_from_logs(db)
    active_analyze = get_active_analyze_from_logs(db)
    latest = get_logs(db, limit=20)
    agent_run = None
    if active_prep and active_prep.get("applicationId"):
        agent_run = get_agent_run(db, str(active_prep["applicationId"]))
    return {
        "success": True,
        "activePrep": active_prep,
        "activeAnalyze": active_analyze,
        "agentRun": agent_run,
        "logs": latest,
        "metrics": get_metrics(db),
    }


@router.post("/qwen/chat")
async def qwen_chat(payload: QwenChatPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import ActivityTimer, append_log

    settings = get_settings(db)
    client = create_llm_client(settings)
    if not client.enabled:
        raise HTTPException(status_code=503, detail="Qwen is not configured. Set llm.model in settings.")

    messages = [
        *[{"role": m["role"], "content": m["content"]} for m in payload.history if m.get("role") and m.get("content")],
        {"role": "user", "content": payload.message},
    ]

    context_note = ""
    from app.services.application_assistant.agent import build_chat_context

    context_note = build_chat_context(db, payload.context)
    if context_note:
        context_note = "\n\n" + context_note

    system = QWEN_SYSTEM_PROMPT + context_note

    with ActivityTimer() as timer:
        result = await client.chat(messages, system=system)

    append_log(
        db,
        event_type="chat",
        model=client.model,
        success=result.get("success", False),
        latency_ms=timer.elapsed_ms,
        summary=f"Chat: {payload.message[:120]}",
        error=result.get("error", ""),
        metadata={
            "usage": result.get("usage", {}),
            "responsePreview": str(result.get("data", ""))[:120],
        },
    )

    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Qwen request failed"))

    return {
        "success": True,
        "reply": result.get("data", ""),
        "usage": result.get("usage", {}),
        "latencyMs": timer.elapsed_ms,
        "model": client.model,
    }


