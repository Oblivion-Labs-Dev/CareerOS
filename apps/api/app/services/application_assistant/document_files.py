"""Materialize stored resume/cover-letter attachments for browser upload."""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import Any

from app.services.application_assistant.domain import AnswerClassification

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "application_assistant"
DOCUMENT_CACHE_DIR = DATA_DIR / "document_cache"

RESUME_FIELD_PATTERNS = [
    r"resume",
    r"\bcv\b",
    r"curriculum\s*vitae",
]

COVER_LETTER_FIELD_PATTERNS = [
    r"cover\s*letter",
]


def _field_text(label: str, name: str = "") -> str:
    return f"{label} {name}".lower()


def is_resume_field(label: str, name: str = "", field_type: str = "") -> bool:
    if field_type and field_type.lower() not in ("file", ""):
        return False
    text = _field_text(label, name)
    return any(re.search(pattern, text, re.I) for pattern in RESUME_FIELD_PATTERNS)


def is_cover_letter_field(label: str, name: str = "", field_type: str = "") -> bool:
    if field_type and field_type.lower() not in ("file", ""):
        return False
    text = _field_text(label, name)
    return any(re.search(pattern, text, re.I) for pattern in COVER_LETTER_FIELD_PATTERNS)


def materialize_attachment(attachment: dict[str, Any] | None) -> Path | None:
    """Write a base64 FileAttachment to a stable cache path for Playwright upload."""
    if not attachment:
        return None

    raw = attachment.get("base64") or attachment.get("data") or ""
    if not raw:
        path_value = attachment.get("path") or attachment.get("filePath")
        if path_value and Path(str(path_value)).is_file():
            return Path(str(path_value))
        return None

    payload = raw.split(",", 1)[-1] if raw.startswith("data:") else raw
    try:
        content = base64.b64decode(payload, validate=False)
    except Exception:
        return None
    if not content:
        return None

    name = (attachment.get("name") or "document.pdf").strip()
    safe_name = re.sub(r"[^\w.\- ]", "_", name) or "document.pdf"
    digest = hashlib.sha256(content).hexdigest()[:16]
    DOCUMENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = DOCUMENT_CACHE_DIR / safe_name
    if dest.exists() and dest.read_bytes() != content:
        stem = Path(safe_name).stem or "document"
        suffix = Path(safe_name).suffix or ".pdf"
        dest = DOCUMENT_CACHE_DIR / f"{stem}_{digest[:8]}{suffix}"
    if not dest.exists() or dest.read_bytes() != content:
        dest.write_bytes(content)
    return dest


def apply_document_fields(fields: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
    """Map resume/cover-letter file inputs to materialized document paths."""
    documents = context.get("documents") or {}
    default_resume = documents.get("defaultResume")
    default_cover = documents.get("defaultCoverLetter")
    resume_path = materialize_attachment(default_resume)
    cover_path = materialize_attachment(default_cover)

    for field in fields:
        if str(field.get("fieldType", "")).lower() != "file":
            continue

        label = str(field.get("label") or "")
        name = str(field.get("name") or "")
        selector = field.get("selectorHint") or (f"[name='{name}']" if name else "")

        if is_resume_field(label, name, "file") and resume_path:
            field["classification"] = AnswerClassification.VERIFIED.value
            field["proposedValue"] = str(resume_path)
            field["documentFileName"] = (default_resume or {}).get("name") or resume_path.name
            field["confidence"] = 1.0
            field["source"] = "documents.defaultResume"
            if selector:
                field["selectorHint"] = selector
            continue

        if is_cover_letter_field(label, name, "file") and cover_path:
            field["classification"] = AnswerClassification.VERIFIED.value
            field["proposedValue"] = str(cover_path)
            field["documentFileName"] = (default_cover or {}).get("name") or cover_path.name
            if selector:
                field["selectorHint"] = selector

    return fields
