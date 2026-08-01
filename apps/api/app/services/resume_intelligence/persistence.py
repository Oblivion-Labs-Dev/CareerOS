"""Persistence for resume intelligence entities."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.store import delete_entity, get_entity, list_entities, new_id, now_iso, upsert_entity

ENTITY_PERSON = "ri_person"
ENTITY_SCAN = "ri_scan"
ENTITY_MATCH = "ri_match"


def list_people(db: Session) -> list[dict[str, Any]]:
    return list_entities(db, ENTITY_PERSON)


def get_person(db: Session, person_id: str) -> dict[str, Any] | None:
    return get_entity(db, ENTITY_PERSON, person_id)


def save_person(db: Session, person: dict[str, Any]) -> dict[str, Any]:
    if not person.get("id"):
        person["id"] = new_id("person_")
    person["updatedAt"] = now_iso()
    if not person.get("createdAt"):
        person["createdAt"] = person["updatedAt"]
    return upsert_entity(db, ENTITY_PERSON, person)


def delete_person(db: Session, person_id: str) -> bool:
    return delete_entity(db, ENTITY_PERSON, person_id)


def list_scans(db: Session, *, person_id: str | None = None) -> list[dict[str, Any]]:
    scans = list_entities(db, ENTITY_SCAN)
    if person_id:
        scans = [s for s in scans if s.get("personId") == person_id]
    return sorted(scans, key=lambda s: s.get("createdAt", ""), reverse=True)


def get_scan(db: Session, scan_id: str) -> dict[str, Any] | None:
    return get_entity(db, ENTITY_SCAN, scan_id)


def save_scan(db: Session, scan: dict[str, Any]) -> dict[str, Any]:
    if not scan.get("id"):
        scan["id"] = new_id("scan_")
    scan["updatedAt"] = now_iso()
    if not scan.get("createdAt"):
        scan["createdAt"] = scan["updatedAt"]
    return upsert_entity(db, ENTITY_SCAN, scan)


def save_match(db: Session, match: dict[str, Any]) -> dict[str, Any]:
    if not match.get("id"):
        match["id"] = new_id("match_")
    match["createdAt"] = now_iso()
    return upsert_entity(db, ENTITY_MATCH, match)


def list_matches(db: Session, *, person_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    matches = list_entities(db, ENTITY_MATCH)
    if person_id:
        matches = [m for m in matches if m.get("personId") == person_id]
    return sorted(matches, key=lambda m: m.get("createdAt", ""), reverse=True)[:limit]
