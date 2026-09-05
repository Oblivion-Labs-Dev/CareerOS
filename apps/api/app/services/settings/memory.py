"""Persistent "what the assistant remembers" preference notes.

A small, user-editable list of durable preferences (e.g. "always keep my
resume to one page") that gets folded into real generation calls as
style/format guidance — never as license to override truth-safety rules.
Wired into `generate_resume_bullets_for_job` via `/resume/tailor`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.store import delete_entity, list_entities, new_id, now_iso, upsert_entity

ENTITY_MEMORY_NOTE = "assistant_memory_note"


def list_memory_notes(db: Session) -> list[dict[str, Any]]:
    notes = list_entities(db, ENTITY_MEMORY_NOTE)
    return sorted(notes, key=lambda n: n.get("createdAt", ""), reverse=True)


def add_memory_note(db: Session, text: str, source: str = "user") -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("Memory note text is empty")
    return upsert_entity(
        db,
        ENTITY_MEMORY_NOTE,
        {"id": new_id("mem_"), "text": text, "source": source, "createdAt": now_iso()},
    )


def delete_memory_note(db: Session, note_id: str) -> bool:
    return delete_entity(db, ENTITY_MEMORY_NOTE, note_id)


def active_memory_text(db: Session, limit: int = 20) -> str:
    """Join active notes into one instruction block for a system prompt."""
    notes = list_memory_notes(db)[:limit]
    return "\n".join(f"- {n['text']}" for n in notes if n.get("text"))
