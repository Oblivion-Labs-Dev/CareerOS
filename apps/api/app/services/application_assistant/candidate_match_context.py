"""Shared candidate context for job matching — profile, resume, and accomplishments."""

from __future__ import annotations

import re
import hashlib
from typing import Any

from app.services.resume_parser import extract_text_from_attachment

# extract_text_from_attachment base64-decodes and re-parses the whole PDF with
# pypdf on every call. The stored defaultResume has no pre-parsed text field,
# so extract_resume_text always fell through to this - fine as a one-off, but
# job matching calls it once per candidate job. Scoring a few hundred queued
# jobs in a refill cycle repeated that full PDF parse a few hundred times in
# the single-threaded uvicorn event loop, pegging one core and blocking every
# other request for tens of seconds. Cache the extracted text per resume
# (keyed by content hash, including equal-length replacements) so
# it is parsed once instead of once per job.
_resume_text_cache: dict[tuple[Any, Any, str], str] = {}


def _cached_resume_text(resume: dict[str, Any]) -> str:
    key = (resume.get("id"), resume.get("mimeType") or resume.get("type"), hashlib.sha256(str(resume.get("base64") or "").encode()).hexdigest())
    cached = _resume_text_cache.get(key)
    if cached is not None:
        return cached
    text = extract_text_from_attachment(resume)
    _resume_text_cache.clear()
    _resume_text_cache[key] = text
    return text


def extract_keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z+#\.]{2,}", text.lower())
    stop_words = {
        "the", "and", "for", "with", "that", "this", "from", "will", "have",
        "are", "was", "been", "being", "our", "your", "you", "all", "can",
        "may", "must", "should", "would", "about", "into", "through",
        "during", "before", "after", "above", "below", "between", "each",
        "other", "some", "such", "than", "too", "very", "just", "also",
    }
    return {w.rstrip(".") for w in words if w not in stop_words and (len(w.rstrip(".")) > 2 or w.rstrip(".") in ("go", "c#"))}


def extract_resume_text(documents: dict[str, Any] | None) -> str:
    if not documents:
        return ""
    resume = documents.get("defaultResume") or {}
    if not isinstance(resume, dict):
        return ""

    for key in ("parsedText", "text", "content", "rawText"):
        value = resume.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    attachment = resume.get("attachment")
    if isinstance(attachment, dict):
        text = _cached_resume_text(attachment)
        if text.strip():
            return text.strip()

    return _cached_resume_text(resume)


# An accomplishment the candidate intends to build is not evidence of anything
# yet. These strings become the resume summary the match scorer reads and the
# tailorer draws on, so a planned project listing Kubernetes would raise match
# scores - and could surface on a resume that Autopilot submits to a real
# employer - for work that does not exist. Planned items stay in the profile so
# the candidate can track them; they just do not count as evidence until the
# status says they shipped.
_UNBUILT_STATUSES = {"planned", "proposed", "idea", "backlog", "not started", "in progress"}


def is_evidenced(item: dict[str, Any]) -> bool:
    """Whether an accomplishment describes work that actually exists."""
    return str(item.get("status") or "").strip().lower() not in _UNBUILT_STATUSES


def accomplishment_text(accomplishments: list[dict[str, Any]] | None) -> str:
    if not accomplishments:
        return ""
    chunks: list[str] = []
    for item in accomplishments:
        if not isinstance(item, dict) or not is_evidenced(item):
            continue
        for key in ("currentBullet", "summary", "title", "technicalChallenge", "architectureDecision"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                chunks.append(value.strip())
        technologies = item.get("technologies")
        if isinstance(technologies, list):
            chunks.extend(str(t).strip() for t in technologies if str(t).strip())
    return "\n".join(chunks)


def work_experience_text(profile: dict[str, Any] | None) -> str:
    if not profile:
        return ""
    chunks: list[str] = []
    for exp in profile.get("workExperience") or []:
        if not isinstance(exp, dict):
            continue
        for key in ("jobTitle", "company", "description"):
            value = exp.get(key)
            if isinstance(value, str) and value.strip():
                chunks.append(value.strip())
    return "\n".join(chunks)


def normalize_profile_skills(profile: dict[str, Any]) -> list[str]:
    skills_field = profile.get("skills")
    normalized: list[str] = []
    if isinstance(skills_field, str):
        normalized = [part.strip().lower() for part in skills_field.split(",") if part.strip()]
    elif isinstance(skills_field, list):
        for item in skills_field:
            if isinstance(item, str) and item.strip():
                normalized.append(item.strip().lower())
            elif isinstance(item, dict):
                name = str(item.get("name") or item.get("label") or "").strip().lower()
                if name:
                    normalized.append(name)
    return normalized


def build_candidate_skill_terms(
    profile: dict[str, Any],
    *,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
) -> set[str]:
    terms: set[str] = set(normalize_profile_skills(profile))
    terms.update(extract_keywords(work_experience_text(profile)))
    terms.update(extract_keywords(extract_resume_text(documents)))
    terms.update(extract_keywords(accomplishment_text(accomplishments)))

    for exp in profile.get("workExperience") or []:
        if not isinstance(exp, dict):
            continue
        terms.update(extract_keywords(str(exp.get("jobTitle") or "")))
        terms.update(extract_keywords(str(exp.get("description") or "")))

    for answer in profile.get("screeningAnswers") or []:
        if isinstance(answer, dict):
            terms.update(extract_keywords(str(answer.get("answer") or "")))

    return {term for term in terms if term}


def _truncate(text: str, limit: int) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def build_candidate_summary_for_llm(
    profile: dict[str, Any],
    *,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
) -> str:
    """Compact candidate context for Qwen job-fit scoring."""
    parts: list[str] = []

    headline = profile.get("headline") or profile.get("targetRole") or profile.get("currentTitle")
    if isinstance(headline, str) and headline.strip():
        parts.append(f"Target/current role: {headline.strip()}")

    years = profile.get("yearsExperience")
    if years:
        parts.append(f"Years of experience: {years}")

    skills = normalize_profile_skills(profile)
    if skills:
        parts.append(f"Skills: {', '.join(skills[:60])}")

    work = work_experience_text(profile)
    if work:
        parts.append(f"Work experience:\n{_truncate(work, 3000)}")

    resume = extract_resume_text(documents)
    if resume:
        parts.append(f"Resume:\n{_truncate(resume, 8000)}")

    accomplishments_blob = accomplishment_text(accomplishments)
    if accomplishments_blob:
        parts.append(f"Accomplishments:\n{_truncate(accomplishments_blob, 3000)}")

    for answer in profile.get("screeningAnswers") or []:
        if not isinstance(answer, dict):
            continue
        question = str(answer.get("question") or answer.get("label") or "").strip()
        value = str(answer.get("answer") or "").strip()
        if question and value:
            parts.append(f"{question}: {value[:500]}")

    location = profile.get("location") or profile.get("city")
    if isinstance(location, str) and location.strip():
        parts.append(f"Location: {location.strip()}")

    return "\n\n".join(parts)


def load_match_context(db: Any) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    from app.db.store import get_kv, list_entities

    profile = get_kv(db, "profile") or {}
    documents = get_kv(db, "documents") or {}
    accomplishments = list_entities(db, "accomplishment")
    return profile, documents, accomplishments


async def match_job_with_context_async(
    db: Any,
    job: dict[str, Any],
    profile: dict[str, Any] | None = None,
    *,
    use_qwen: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    from app.services.application_assistant.qwen_job_match import match_job_with_qwen_fallback

    return await match_job_with_qwen_fallback(
        db,
        job,
        profile,
        use_qwen=use_qwen,
        **kwargs,
    )


def match_job_with_context(
    db: Any,
    job: dict[str, Any],
    profile: dict[str, Any] | None = None,
    *,
    use_qwen: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    from app.services.application_assistant.qwen_job_match import match_job_with_qwen_fallback_sync

    return match_job_with_qwen_fallback_sync(
        db,
        job,
        profile,
        use_qwen=use_qwen,
        **kwargs,
    )


def match_sources_used(
    profile: dict[str, Any],
    *,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
) -> dict[str, bool]:
    return {
        "profile": bool(profile),
        "resume": bool(extract_resume_text(documents)),
        "accomplishments": bool(accomplishment_text(accomplishments)),
        "workExperience": bool(work_experience_text(profile)),
    }
