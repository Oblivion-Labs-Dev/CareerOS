"""Application Assistant API routes — settings domain."""

from ._common import *  # noqa: F401,F403

router = APIRouter(prefix="/application-assistant", tags=["application-assistant"])


# ── Settings ──────────────────────────────────────────────────────────────────

@router.get("/settings")
def get_aa_settings(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "settings": get_settings(db)}


@router.post("/settings")
def update_aa_settings(payload: SettingsPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    patch = payload.model_dump(exclude_none=True)
    return {"success": True, "settings": save_settings(db, patch)}


@router.get("/providers")
def get_providers() -> dict[str, Any]:
    return {"success": True, "providers": list_providers()}


