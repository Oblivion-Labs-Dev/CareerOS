"""One-page preview/download of minimal edits to the approved resume."""
from __future__ import annotations

import base64
import re
import time

from app.services.resume_intelligence.minimal_tailoring import tailor, TailoringConfig
from app.services.resume_intelligence.baseline_document import render_baseline


def generate_studio(records: list[dict], profile: dict, description: str, title: str = "", company: str = "") -> dict:
    if len(description.strip()) < 40:
        raise ValueError("Paste a full job description (at least 40 characters).")
    started = time.perf_counter()
    config = TailoringConfig(**(profile.get("resumeTailoringConfig") or {}))
    result = tailor(records, description, title, config=config)
    pdf = render_baseline(result)
    import pymupdf
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        png = document[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).tobytes("png")
    return {"result": result, "pdfBase64": base64.b64encode(pdf).decode(), "previewBase64": base64.b64encode(png).decode(),
            "pageCount": 1, "elapsedMs": round((time.perf_counter() - started) * 1000), "omittedForFit": 0,
            "filename": re.sub(r"[^a-zA-Z0-9_-]+", "-", f"Resume-{company or title or 'Tailored'}").strip("-") + ".pdf"}
