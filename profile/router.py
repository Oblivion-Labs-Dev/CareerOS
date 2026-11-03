"""FastAPI routes for the profile service.

Paths are kept identical to the pre-refactor router (no ``/profile`` prefix is
added here); ``main.py`` includes this router without a prefix during the
transition so existing frontend/extension calls keep resolving.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from profile import service as profile_service
from profile.memory import add_memory_note, delete_memory_note, list_memory_notes
from profile.portfolio import (
    build_public_portfolio,
    get_portfolio_settings,
    save_portfolio_settings,
)
from profile.schemas import MemoryNotePayload, PortfolioSettingsPayload, ProfilePayload
from shared.deps import db_session

router = APIRouter()


@router.get("/profile")
def get_profile(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"profile": profile_service.get_profile(db)}


@router.post("/profile")
def upsert_profile(payload: ProfilePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    profile = profile_service.update_profile(db, payload.profile)
    return {"success": True, "profile": profile}


@router.get("/settings/memory")
def list_assistant_memory(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "notes": list_memory_notes(db)}


@router.post("/settings/memory")
def add_assistant_memory(payload: MemoryNotePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    try:
        note = add_memory_note(db, payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"success": True, "note": note}


@router.delete("/settings/memory/{note_id}")
def delete_assistant_memory(note_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    deleted = delete_memory_note(db, note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory note not found")
    return {"success": True}


@router.get("/settings/portfolio")
def get_portfolio_settings_route(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "settings": get_portfolio_settings(db)}


@router.patch("/settings/portfolio")
def update_portfolio_settings_route(
    payload: PortfolioSettingsPayload, db: Session = Depends(db_session)
) -> dict[str, Any]:
    try:
        updated = save_portfolio_settings(db, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"success": True, "settings": updated}


@router.get("/public/portfolio/{slug}")
def get_public_portfolio(slug: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    portfolio = build_public_portfolio(db, slug)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="This portfolio isn't public.")
    return {"success": True, "portfolio": portfolio}
