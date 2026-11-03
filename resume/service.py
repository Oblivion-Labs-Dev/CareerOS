"""Resume service facade.

Thin orchestration over the resume modules (parsers, profiles store, tailoring,
ats scoring). It implements :class:`resume.interfaces.IResumeService` so other
services depend on the interface rather than the concrete modules. The heavy
lifting stays in the dedicated modules; this file exists to give the package a
single, stable public entry point.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.db.store import get_kv, set_kv
from resume import resume_profiles
from resume.parsers.pdf_parser import parse_resume_into_profile


def get_profile(db: Session) -> dict[str, Any]:
    return get_kv(db, "profile") or {}


def update_profile(db: Session, patch: dict[str, Any]) -> dict[str, Any]:
    current = get_kv(db, "profile") or {}
    merged = {**current, **patch}
    set_kv(db, "profile", merged)
    return merged


def parse_resume(db: Session, force: bool = False) -> dict[str, Any]:
    profile = get_kv(db, "profile") or {}
    documents = get_kv(db, "documents") or {}
    result = parse_resume_into_profile(profile, documents, force=force)
    set_kv(db, "profile", result["profile"])
    return result


def get_default_resume(db: Session) -> dict[str, Any] | None:
    documents = get_kv(db, "documents") or {}
    return documents.get("defaultResume")


def save_default_resume(db: Session, resume: dict[str, Any]) -> dict[str, Any]:
    from shared.db import new_id, now_iso

    documents = get_kv(db, "documents") or {"defaultResume": None, "defaultCoverLetter": None}
    stored = {**resume, "id": resume.get("id") or new_id("resume_"), "updatedAt": now_iso()}
    documents["defaultResume"] = stored
    set_kv(db, "documents", documents)
    return stored


def list_resume_profiles(db: Session) -> list[dict[str, Any]]:
    return resume_profiles.list_resume_profiles(db)
