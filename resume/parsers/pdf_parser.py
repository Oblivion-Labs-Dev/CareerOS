import base64
import io
import re
from typing import Any

from pypdf import PdfReader

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
YEARS_RE = re.compile(r"(\d{1,2})\+?\s*years?\s+(?:of\s+)?experience", re.I)


def extract_text_from_attachment(attachment: dict[str, Any] | None) -> str:
    if not attachment or not attachment.get("base64"):
        return ""
    try:
        raw = base64.b64decode(attachment["base64"], validate=True)
        mime = attachment.get("type") or attachment.get("mimeType") or ""
        if "pdf" in mime.lower() or attachment.get("name", "").lower().endswith(".pdf"):
            reader = PdfReader(io.BytesIO(raw))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        # Saved documents are optional matching context. A stale, truncated, or
        # incorrectly labelled attachment must not abort job import or scoring.
        return ""


def parse_resume_fields(text: str, profile: dict[str, Any], *, force: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    extracted: dict[str, Any] = {}
    updated = dict(profile)

    def _set(key: str, value: object) -> None:
        extracted[key] = value
        if force or not updated.get(key):
            updated[key] = value

    email = EMAIL_RE.search(text)
    if email:
        _set("email", email.group(0))

    phone = PHONE_RE.search(text)
    if phone:
        _set("phone", phone.group(0))

    years = YEARS_RE.search(text)
    if years:
        _set("yearsExperience", years.group(1))

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        name = lines[0]
        _set("fullName", name)
        parts = name.split()
        if len(parts) >= 2:
            _set("firstName", parts[0])
            _set("lastName", " ".join(parts[1:]))

    # Structure: employment history, education and skills. Until this existed
    # the four regexes above were the whole parser, so a profile built by
    # uploading a résumé still had no employers, no degrees and no dates - all
    # of which application forms ask for, and all of which had to be typed in
    # by hand afterwards.
    #
    # Structured values are always reported in `extracted`, but only written
    # into the profile when it holds nothing there already — unless force=True,
    # which is the user explicitly re-scanning a new resume.
    from resume.parsers.structure_parser import parse_structure

    for key, value in parse_structure(text).items():
        if not value:
            continue
        extracted[key] = value
        if force or not updated.get(key):
            updated[key] = value

    return updated, extracted


def parse_resume_into_profile(
    profile: dict[str, Any],
    documents: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    resume = documents.get("defaultResume")
    if not resume:
        raise ValueError("No default resume uploaded")

    needs_parse = force or not profile.get("email") or not profile.get("phone")
    if not needs_parse:
        return {"profile": profile, "extracted": {}, "textPreview": ""}

    text = extract_text_from_attachment(resume)
    if not text.strip():
        raise ValueError("Could not extract text from resume")

    updated, extracted = parse_resume_fields(text, profile, force=force)
    return {
        "profile": updated,
        "extracted": extracted,
        "textPreview": text[:1200],
    }
