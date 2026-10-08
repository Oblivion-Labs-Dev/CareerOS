"""Export re-validates resume.json against career.json, renders it into the golden DOCX, and lets Word confirm one page.

The DOCX and the PDF come from the same render as the preview; the PDF is Word's own conversion of that DOCX.
"""
from __future__ import annotations

from typing import Any, Literal

from app.services.career_compiler.docx_render import WordMeasurer, render_docx
from app.services.career_compiler.docx_template import load_golden, load_spec, template_digest
from app.services.career_compiler.models import ResumeDocument
from app.services.career_compiler.store import CareerStore, load_store
from app.services.career_compiler.validator import validate_document


def export(result: dict, fmt: Literal["docx", "pdf"] = "docx", *, store: CareerStore | None = None,
           spec: dict[str, Any] | None = None, golden: bytes | None = None, measurer=None) -> bytes:
    store = store or load_store()
    spec = spec or load_spec()
    document = ResumeDocument.model_validate(result)
    if document.template_digest != template_digest(spec):
        raise ValueError("This resume was generated for a different template. Regenerate it.")
    issues = validate_document(document, store)
    if issues:
        raise ValueError("; ".join(f"{i.bullet_id}: {i.message}" for i in issues[:6]))
    rendered = render_docx(document, spec, golden or load_golden())
    measured = (measurer or WordMeasurer(spec)).measure(rendered)
    if not measured.fits:
        raise ValueError(f"The resume renders on {measured.pages} pages in {measured.engine}. Regenerate to refit it.")
    if fmt == "pdf":
        if measured.pdf is None:
            raise ValueError("PDF export needs Word or LibreOffice on the API server.")
        return measured.pdf
    return rendered.docx


def export_pdf(result: dict, **kwargs) -> bytes:
    return export(result, "pdf", **kwargs)
