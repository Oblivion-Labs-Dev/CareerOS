from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.services.error_fix_tracker import error_fix_tracker
from app.services.repair.processor import latest_manual_run, process_logs_and_errors

router = APIRouter(prefix="/dev/repair", tags=["dev-repair"])


@router.post("/process-logs")
def manual_process_logs() -> dict:
    if not settings.career_os_dev_mode:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        result = process_logs_and_errors()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"success": result.get("state") == "completed", **result}


@router.get("/latest-run")
def get_latest_run() -> dict:
    if not settings.career_os_dev_mode:
        raise HTTPException(status_code=404, detail="Not found")
    run = latest_manual_run()
    if not run:
        return {"state": "idle", "run": None}
    return {"state": run.get("state", "idle"), "run": run}


@router.post("/reconcile-errors")
def reconcile_errors() -> dict:
    if not settings.career_os_dev_mode:
        raise HTTPException(status_code=404, detail="Not found")
    recorded = error_fix_tracker.reconcile_resolved_errors()
    snapshot = error_fix_tracker.snapshot()
    return {
        "success": True,
        "fixesRecorded": recorded,
        "unresolvedErrors": snapshot.get("unresolvedErrors", 0),
        "totalFixesTracked": snapshot.get("totalFixesTracked", 0),
    }
