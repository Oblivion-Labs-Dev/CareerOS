"""Application Assistant API routes — llm_metrics domain."""

from ._common import *  # noqa: F401,F403

router = APIRouter(prefix="/application-assistant", tags=["application-assistant"])


@router.get("/llm-metrics")
def get_llm_metrics() -> dict[str, Any]:
    """Which model actually answered each LLM call since the backend last restarted,
    across every flow (form-field self-healing, code-patch self-healing, answer
    resolution, etc.) — counts are process-wide, not per-run."""
    from app.services.application_assistant.llm_client import llm_call_metrics

    return {"success": True, "metrics": llm_call_metrics.to_dict()}


@router.post("/llm-metrics/reset")
def reset_llm_metrics() -> dict[str, Any]:
    from app.services.application_assistant.llm_client import llm_call_metrics

    llm_call_metrics.reset()
    return {"success": True}
