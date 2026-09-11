"""Full-mailbox Gmail archive: sync once, read from the database after.

Separate from the existing /email routes, which fetch from IMAP on every call
and cap at 100-150 of the newest messages. Those remain for the live-inbox view;
these exist so the account's whole application history is held locally and never
re-downloaded.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.store import session_scope
from app.routers.api import db_session
from app.services.tracker import gmail_archive

router = APIRouter(prefix="/email/archive", tags=["email-archive"])


@router.get("")
def read(
    limit: int = Query(default=100, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default=""),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Read stored mail. Opens no IMAP connection."""
    return {"success": True, **gmail_archive.read_archive(db, limit=limit, offset=offset, query=q)}


@router.get("/status")
def status(db: Session = Depends(db_session)) -> dict[str, Any]:
    state = gmail_archive.load_state(db)
    return {
        "success": True,
        "stored": state.get("totalStored", 0),
        "highestUid": state.get("highestUid", 0),
        "uidValidity": state.get("uidValidity", ""),
        "lastSyncAt": state.get("lastSyncAt"),
        "synced": bool(state.get("lastSyncAt")),
    }


@router.post("/sync")
def sync(
    full: bool = Query(default=False, description="re-scan the whole mailbox"),
    maxMessages: int | None = Query(default=None, ge=1, le=20000),
) -> dict[str, Any]:
    """Fetch everything not already stored.

    No Depends(db_session): a first sync over a large mailbox runs for minutes,
    and holding a pooled connection for that long starves the rest of the API -
    the same pool exhaustion the tailoring routes were changed to avoid.
    """
    with session_scope() as db:
        report = gmail_archive.sync_archive(db, force_full=full, max_messages=maxMessages)
    return report.to_dict()
