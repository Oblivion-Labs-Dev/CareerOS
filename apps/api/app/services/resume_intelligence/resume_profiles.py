"""Multi-profile resume storage.

A "resume profile" is a named, switchable resume — e.g. "Default", "Fintech",
"Staff+ track". Exactly one profile is marked default at a time; the default
profile's resume is mirrored into the legacy `documents.defaultResume` KV slot
so the rest of the app (autofill, job relevancy, cover letters — anything
still reading `documents.defaultResume`) keeps working unchanged.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.store import (
    delete_entity,
    get_entity,
    get_kv,
    list_entities,
    new_id,
    now_iso,
    set_kv,
    upsert_entity,
)

ENTITY_RESUME_PROFILE = "resume_profile"


def _sync_default_document(db: Session, profile: dict[str, Any]) -> None:
    """Mirror a profile's resume into documents.defaultResume for backward compatibility."""
    if not profile.get("resume"):
        return
    documents = get_kv(db, "documents") or {"defaultResume": None, "defaultCoverLetter": None}
    documents["defaultResume"] = profile["resume"]
    set_kv(db, "documents", documents)


def list_resume_profiles(db: Session) -> list[dict[str, Any]]:
    profiles = list_entities(db, ENTITY_RESUME_PROFILE)
    if not profiles:
        # Migrate the single legacy default resume into an initial "Default" profile.
        documents = get_kv(db, "documents") or {}
        legacy_resume = documents.get("defaultResume")
        seeded = upsert_entity(
            db,
            ENTITY_RESUME_PROFILE,
            {
                "id": new_id("resprof_"),
                "name": "Default",
                "isDefault": True,
                "resume": legacy_resume,
                "createdAt": now_iso(),
            },
        )
        return [seeded]
    return sorted(profiles, key=lambda p: (not p.get("isDefault"), p.get("createdAt", "")))


def get_resume_profile(db: Session, profile_id: str) -> dict[str, Any] | None:
    return get_entity(db, ENTITY_RESUME_PROFILE, profile_id)


def get_default_resume_profile(db: Session) -> dict[str, Any] | None:
    for profile in list_resume_profiles(db):
        if profile.get("isDefault"):
            return profile
    return None


def create_resume_profile(db: Session, name: str, resume: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = list_resume_profiles(db)
    is_first = len(existing) == 0
    profile = upsert_entity(
        db,
        ENTITY_RESUME_PROFILE,
        {
            "id": new_id("resprof_"),
            "name": name.strip() or "Untitled profile",
            "isDefault": is_first,
            "resume": resume,
            "createdAt": now_iso(),
        },
    )
    if is_first:
        _sync_default_document(db, profile)
    return profile


def update_resume_profile(db: Session, profile_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    current = get_resume_profile(db, profile_id)
    if not current:
        return None
    merged = {**current, **patch, "id": profile_id, "updatedAt": now_iso()}
    saved = upsert_entity(db, ENTITY_RESUME_PROFILE, merged)
    if saved.get("isDefault"):
        _sync_default_document(db, saved)
    return saved


def delete_resume_profile(db: Session, profile_id: str) -> bool:
    profile = get_resume_profile(db, profile_id)
    if not profile:
        return False
    was_default = bool(profile.get("isDefault"))
    deleted = delete_entity(db, ENTITY_RESUME_PROFILE, profile_id)
    if deleted and was_default:
        remaining = list_entities(db, ENTITY_RESUME_PROFILE)
        if remaining:
            remaining.sort(key=lambda p: p.get("createdAt", ""))
            set_default_resume_profile(db, remaining[0]["id"])
    return deleted


def set_default_resume_profile(db: Session, profile_id: str) -> dict[str, Any] | None:
    target = get_resume_profile(db, profile_id)
    if not target:
        return None
    for profile in list_entities(db, ENTITY_RESUME_PROFILE):
        if profile.get("id") == profile_id:
            continue
        if profile.get("isDefault"):
            upsert_entity(db, ENTITY_RESUME_PROFILE, {**profile, "isDefault": False})
    updated = upsert_entity(db, ENTITY_RESUME_PROFILE, {**target, "isDefault": True, "updatedAt": now_iso()})
    _sync_default_document(db, updated)
    return updated
