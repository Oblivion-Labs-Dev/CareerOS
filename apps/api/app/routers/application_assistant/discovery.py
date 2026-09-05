"""Application Assistant API routes — discovery domain."""

from ._common import *  # noqa: F401,F403

router = APIRouter(prefix="/application-assistant", tags=["application-assistant"])


# ── Discovery ─────────────────────────────────────────────────────────────────

@router.post("/discovery/start")
async def start_discovery(payload: DiscoveryStartPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    valid, reason = validate_url(payload.careersUrl)
    if not valid:
        raise HTTPException(status_code=400, detail=reason)

    run = create_discovery_run(db, payload.model_dump())
    await run_in_background(run["id"], run_discovery(run["id"]))
    return {"success": True, "run": run}


@router.get("/discovery/{run_id}")
def get_discovery_status(run_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    run = get_discovery_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Discovery run not found")
    return {"success": True, "run": run, "taskStatus": task_status(run_id)}


@router.post("/discovery/{run_id}/cancel")
def cancel_discovery_run(run_id: str) -> dict[str, Any]:
    cancelled = cancel_discovery(run_id)
    return {"success": cancelled}


@router.get("/discovery")
def list_runs(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "runs": list_discovery_runs(db)}


