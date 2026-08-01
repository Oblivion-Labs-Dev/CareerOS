"""Tests for resume/cover-letter upload support."""

from __future__ import annotations

import base64
from pathlib import Path

from app.services.application_assistant.document_files import (
    apply_document_fields,
    is_resume_field,
    materialize_attachment,
)

MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def test_is_resume_field_detects_common_labels() -> None:
    assert is_resume_field("Resume/CV *", "resume", "file") is True
    assert is_resume_field("Upload CV", "", "file") is True
    assert is_resume_field("LinkedIn Profile", "linkedin", "url") is False


def test_materialize_attachment_writes_cache_file(tmp_path, monkeypatch) -> None:
    import app.services.application_assistant.document_files as mod

    monkeypatch.setattr(mod, "DOCUMENT_CACHE_DIR", tmp_path)
    attachment = {
        "name": "Akshay_Borse_Resume.pdf",
        "type": "application/pdf",
        "base64": "data:application/pdf;base64," + base64.b64encode(MINIMAL_PDF).decode(),
    }
    path = materialize_attachment(attachment)
    assert path is not None
    assert path.is_file()
    assert path.name == "Akshay_Borse_Resume.pdf"
    assert path.read_bytes() == MINIMAL_PDF


def test_apply_document_fields_maps_resume_file_input(tmp_path, monkeypatch) -> None:
    import app.services.application_assistant.document_files as mod

    monkeypatch.setattr(mod, "DOCUMENT_CACHE_DIR", tmp_path)
    resume_path = tmp_path / "resume.pdf"
    resume_path.write_bytes(MINIMAL_PDF)
    fields = [
        {
            "label": "Resume/CV *",
            "normalizedKey": "resume_cv",
            "fieldType": "file",
            "name": "resume",
            "selectorHint": "#resume",
            "classification": "unknown",
        }
    ]
    context = {
        "documents": {
            "defaultResume": {
                "name": "resume.pdf",
                "type": "application/pdf",
                "base64": base64.b64encode(MINIMAL_PDF).decode(),
            }
        }
    }
    updated = apply_document_fields(fields, context)
    assert updated[0]["classification"] == "verified"
    assert Path(updated[0]["proposedValue"]).is_file()
    assert updated[0]["source"] == "documents.defaultResume"
