"""Application Assistant API routes — llm domain."""

from ._common import *  # noqa: F401,F403

router = APIRouter(prefix="/application-assistant", tags=["application-assistant"])


# ── LLM ───────────────────────────────────────────────────────────────────────

@router.post("/llm/test")
async def test_llm(db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import update_connection_status

    settings = get_settings(db)
    client = create_llm_client(settings)
    result = await client.test_connection()
    model = settings.get("llm", {}).get("model", "")
    if result.get("models") and not model:
        model = result["models"][0] if result["models"] else ""
    update_connection_status(db, connected=result.get("success", False), model=model)
    return {"success": result.get("success", False), **result}


