"""One-page preview/download of minimal edits to the approved resume."""
from __future__ import annotations

import base64
import re
import time
from dataclasses import replace

from app.services.resume_intelligence.minimal_tailoring import tailor, mode_config
from app.services.resume_intelligence.baseline_document import render_baseline, approved_path
from app.services.resume_intelligence.evidence_match import compare_pdfs


def generate_studio(records: list[dict], profile: dict, description: str, title: str = "", company: str = "", mode: str = "honest", use_semantic: bool | None = None) -> dict:
    if len(description.strip()) < 40:
        raise ValueError("Paste a full job description (at least 40 characters).")
    started = time.perf_counter()
    try:
        config = mode_config(mode, profile.get("resumeTailoringConfig"))
        if use_semantic is not None:
            if not isinstance(use_semantic, bool):
                raise ValueError("Semantic ranking must be a boolean.")
            config = replace(config, use_semantic=use_semantic and mode != "off")
    except TypeError as exc:
        raise ValueError("Check the saved resumeTailoringConfig settings.") from exc
    result = tailor(records, description, title, config=config, mode=mode)
    pdf = render_baseline(result)
    comparison = compare_pdfs(approved_path().read_bytes(), pdf, description,
                             use_semantic=config.use_semantic, bm25_k1=config.bm25_k1,
                             bm25_b=config.bm25_b, rrf_k=config.rrf_k)
    import pymupdf
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        png = document[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).tobytes("png")
    return {"result": result, "matchComparison": comparison, "pdfBase64": base64.b64encode(pdf).decode(), "previewBase64": base64.b64encode(png).decode(),
            "pageCount": 1, "elapsedMs": round((time.perf_counter() - started) * 1000), "omittedForFit": 0,
            "filename": re.sub(r"[^a-zA-Z0-9_-]+", "-", f"Resume-{company or title or 'Tailored'}").strip("-") + ".pdf"}
