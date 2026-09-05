"""Intelligence Layer API routes — JobPilot features in CareerOS."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.store import session_scope
from app.services.answer_engine import generate_answer, load_custom_answers
from app.services.intelligence import auto_apply, auto_apply_lanes, night_shift, signals, tasks

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


def db_session():
    with session_scope() as db:
        yield db


# ── Tasks / CIOS ────────────────────────────────────────────────────────────

class TaskTickPayload(BaseModel):
    period: str = "daily"
    key: str
    done: bool = True
    notes: str = ""


@router.get("/tasks/today")
def intelligence_tasks_today(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, **tasks.get_today(db)}


@router.get("/tasks/week")
def intelligence_tasks_week(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, **tasks.get_week(db)}


@router.post("/tasks/tick")
def intelligence_tasks_tick(payload: TaskTickPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    if payload.period not in {"daily", "weekly"}:
        raise HTTPException(status_code=400, detail="period must be daily or weekly")
    return tasks.tick_task(db, period=payload.period, key=payload.key, done=payload.done, notes=payload.notes)


@router.get("/tasks/artifacts")
def intelligence_task_artifacts(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "artifacts": tasks.list_artifacts(db)}


# ── Signals ─────────────────────────────────────────────────────────────────

@router.get("/signals")
def intelligence_list_signals(
    db: Session = Depends(db_session),
    min_intent: int = Query(default=50, ge=0, le=100),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    return {"success": True, **signals.list_signals(db, min_intent=min_intent, page=page, per_page=per_page)}


@router.get("/signals/stats")
def intelligence_signal_stats(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, **signals.get_stats(db)}


@router.post("/signals/scan")
def intelligence_signal_scan(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, **signals.trigger_scan(db)}


@router.get("/signals/contacts")
def intelligence_signal_contacts(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, **signals.list_contacts(db)}


# ── Night Shift ─────────────────────────────────────────────────────────────

@router.get("/night-shift/settings")
def night_shift_get_settings(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "settings": night_shift.get_settings(db)}


@router.put("/night-shift/settings")
def night_shift_update_settings(body: dict[str, Any], db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "settings": night_shift.update_settings(db, body)}


@router.post("/night-shift/select")
def night_shift_select(dry_run: bool = False, db: Session = Depends(db_session)) -> dict[str, Any]:
    return night_shift.select_for_night_shift(db, dry_run=dry_run)


@router.get("/night-shift/queue")
def night_shift_queue(
    db: Session = Depends(db_session),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict[str, Any]:
    items = night_shift.get_queue(db, status=status, limit=limit)
    return {"success": True, "queue": items, "total": len(items)}


@router.post("/night-shift/queue/{item_id}")
def night_shift_update_item(item_id: str, body: dict[str, Any], db: Session = Depends(db_session)) -> dict[str, Any]:
    if not night_shift.update_queue_item(db, item_id, body):
        raise HTTPException(status_code=404, detail="Queue item not found")
    return {"success": True}


@router.get("/night-shift/tiers")
def night_shift_tiers() -> dict[str, Any]:
    return {"success": True, **night_shift.get_tiers()}


# ── Auto Apply ──────────────────────────────────────────────────────────────

@router.get("/auto-apply/settings")
def auto_apply_get_settings(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "settings": auto_apply.get_settings(db)}


@router.put("/auto-apply/settings")
def auto_apply_update_settings(body: dict[str, Any], db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "settings": auto_apply.update_settings(db, body)}


@router.post("/auto-apply/run")
def auto_apply_run(dry_run: bool = True, db: Session = Depends(db_session)) -> dict[str, Any]:
    return auto_apply.run_auto_apply(db, dry_run=dry_run)


@router.get("/auto-apply/log")
def auto_apply_log(db: Session = Depends(db_session), limit: int = Query(default=50, ge=1, le=100)) -> dict[str, Any]:
    return {"success": True, "log": auto_apply.get_log(db, limit=limit)}


# ── Auto Apply Lanes ────────────────────────────────────────────────────────

class LaneFiltersPayload(BaseModel):
    includeKeywords: str = ""
    excludeKeywords: str = ""
    location: str = ""
    company: str = ""
    freshness: str = "all"


class LaneCreatePayload(BaseModel):
    name: str
    filters: LaneFiltersPayload = LaneFiltersPayload()
    matchBar: int = 60
    dailyCap: int = 5
    reviewBeforeSubmit: bool = True
    enabled: bool = True


class LanePatchPayload(BaseModel):
    name: str | None = None
    filters: LaneFiltersPayload | None = None
    matchBar: int | None = None
    dailyCap: int | None = None
    reviewBeforeSubmit: bool | None = None
    enabled: bool | None = None


class SharedCapPayload(BaseModel):
    dailyCap: int


@router.get("/auto-apply/status")
def auto_apply_lanes_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, **auto_apply_lanes.get_status(db)}


@router.get("/auto-apply/lanes")
def auto_apply_lanes_list(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "lanes": auto_apply_lanes.list_lanes(db)}


@router.post("/auto-apply/lanes")
def auto_apply_lanes_create(payload: LaneCreatePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    try:
        lane = auto_apply_lanes.create_lane(db, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "lane": lane}


@router.patch("/auto-apply/lanes/{lane_id}")
def auto_apply_lanes_update(lane_id: str, payload: LanePatchPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    try:
        lane = auto_apply_lanes.update_lane(db, lane_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not lane:
        raise HTTPException(status_code=404, detail="Lane not found")
    return {"success": True, "lane": lane}


@router.delete("/auto-apply/lanes/{lane_id}")
def auto_apply_lanes_delete(lane_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    if not auto_apply_lanes.delete_lane(db, lane_id):
        raise HTTPException(status_code=404, detail="Lane not found")
    return {"success": True}


@router.put("/auto-apply/cap")
def auto_apply_lanes_set_cap(payload: SharedCapPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, **auto_apply_lanes.set_shared_cap(db, payload.dailyCap)}


@router.post("/auto-apply/lanes/run")
async def auto_apply_lanes_run(dry_run: bool = True, db: Session = Depends(db_session)) -> dict[str, Any]:
    return await auto_apply_lanes.evaluate_lanes(db, dry_run=dry_run)


@router.get("/auto-apply/lanes/log")
def auto_apply_lanes_log(db: Session = Depends(db_session), limit: int = Query(default=20, ge=1, le=50)) -> dict[str, Any]:
    return {"success": True, "log": auto_apply_lanes.get_run_log(db, limit=limit)}


# ── Answer Bank ─────────────────────────────────────────────────────────────

class AnswerLookupPayload(BaseModel):
    question: str
    company: str = ""
    roleTitle: str = ""


@router.get("/answers/bank")
def intelligence_answer_bank() -> dict[str, Any]:
    return {"success": True, "answers": load_custom_answers()}


@router.post("/answers/lookup")
def intelligence_answer_lookup(payload: AnswerLookupPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.db.store import get_kv

    profile = get_kv(db, "profile") or {}
    answer = generate_answer(payload.question, company=payload.company, role_title=payload.roleTitle, profile=profile)
    return {"success": True, "answer": answer, "question": payload.question}
