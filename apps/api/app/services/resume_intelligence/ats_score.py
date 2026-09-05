"""Deterministic ATS-readiness scoring for a resume.

Every checklist item below reflects a real, explainable check run against the
resume's extracted text (and, optionally, a target job description) — nothing
here is decorative. Score is a simple weighted pass count, not a black box.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.resume_intelligence.scanner import extract_text_from_upload

_SECTION_HEADERS = {
    "experience": re.compile(r"\b(experience|employment history|work history)\b", re.I),
    "education": re.compile(r"\beducation\b", re.I),
    "skills": re.compile(r"\bskills\b", re.I),
}

_BULLET_RE = re.compile(r"^[\s]*[•●▪\-*]\s+", re.M)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z+.#/-]{1,}")


def _checklist_item(label: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"label": label, "passed": passed, "detail": detail}


def compute_ats_score(
    resume: dict[str, Any] | None,
    job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not resume:
        return {
            "score": 0,
            "checklist": [
                _checklist_item("Resume on file", False, "No resume uploaded to this profile yet."),
            ],
        }

    text = extract_text_from_upload(
        base64_data=resume.get("base64", ""),
        mime_type=resume.get("mimeType") or resume.get("type") or "",
        filename=resume.get("name") or "",
    )

    checklist: list[dict[str, Any]] = []

    # 1. Parseable text — a scanned/image-only PDF extracts to near-nothing.
    parseable = len(text.strip()) >= 200
    checklist.append(
        _checklist_item(
            "Parseable text",
            parseable,
            f"Extracted {len(text.strip())} characters of selectable text."
            if parseable
            else "Fewer than 200 characters extracted — this looks like a scanned image or an unreadable file, which most ATS parsers reject.",
        )
    )

    # 2. Semantic section headings.
    found_sections = [name for name, pattern in _SECTION_HEADERS.items() if pattern.search(text)]
    has_sections = len(found_sections) >= 2
    checklist.append(
        _checklist_item(
            "Standard section headings",
            has_sections,
            f"Found: {', '.join(s.title() for s in found_sections)}."
            if found_sections
            else "No Experience/Education/Skills headings detected — ATS parsers key off these to segment your resume.",
        )
    )

    # 3. Bullet-point structure (scannable achievements vs. dense paragraphs).
    bullet_count = len(_BULLET_RE.findall(text))
    has_bullets = bullet_count >= 3
    checklist.append(
        _checklist_item(
            "Scannable bullet points",
            has_bullets,
            f"{bullet_count} bulleted lines detected."
            if bullet_count
            else "No bullet markers detected — dense paragraphs are harder for both ATS parsers and recruiters to scan.",
        )
    )

    # 4. Reasonable length (roughly 300–1200 words — one to two pages of real content).
    word_count = len(_WORD_RE.findall(text))
    reasonable_length = 300 <= word_count <= 1400
    checklist.append(
        _checklist_item(
            "Reasonable length",
            reasonable_length,
            f"{word_count} words."
            + (
                " Too short to demonstrate depth."
                if word_count < 300
                else " Longer than ~2 pages of content — ATS systems and recruiters both tend to skim past this."
                if word_count > 1400
                else ""
            ),
        )
    )

    # 5. Keyword coverage against a target job, when one is given.
    job_description = ""
    job_title = ""
    if job:
        job_description = str(job.get("description") or job.get("descriptionText") or "")
        job_title = str(job.get("title") or job.get("roleTitle") or "")

    if job_description:
        from app.services.resume_intelligence.match_engine import build_ats_keyword_sets

        keyword_sets = build_ats_keyword_sets(job_description, job_title)
        all_keywords = [kw for group in keyword_sets.values() for kw in group]
        text_lower = text.lower()
        matched = [kw for kw in all_keywords if kw.lower() in text_lower]
        coverage = (len(matched) / len(all_keywords)) if all_keywords else 1.0
        keyword_pass = coverage >= 0.5
        checklist.append(
            _checklist_item(
                "Keyword coverage for this role",
                keyword_pass,
                f"{len(matched)}/{len(all_keywords)} JD keywords present ({round(coverage * 100)}%)."
                if all_keywords
                else "Could not extract keywords from this job description.",
            )
        )
    else:
        keyword_pass = None  # not scored — no job context given

    scored_items = [c for c in checklist if True]
    passed_count = sum(1 for c in scored_items if c["passed"])
    score = round((passed_count / len(scored_items)) * 100) if scored_items else 0

    return {"score": score, "checklist": checklist, "wordCount": word_count}
