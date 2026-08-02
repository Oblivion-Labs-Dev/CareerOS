"""Resume scan orchestration."""

from __future__ import annotations

import base64
import io
from typing import Any

from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.db.store import list_entities, new_id, upsert_entity
from app.services.resume_intelligence.persistence import save_scan
from app.services.resume_intelligence.qwen_services import extract_resume_with_qwen
from app.services.resume_parser import parse_resume_fields


def extract_text_from_upload(*, text: str = "", base64_data: str = "", mime_type: str = "", filename: str = "") -> str:
    if text.strip():
        return text.strip()
    if not base64_data:
        return ""
    raw = base64.b64decode(base64_data)
    is_pdf = "pdf" in mime_type.lower() or filename.lower().endswith(".pdf")
    if is_pdf:
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    try:
        return raw.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def deterministic_scan_fields(text: str) -> dict[str, Any]:
    profile_stub: dict[str, Any] = {}
    updated, extracted = parse_resume_fields(text, profile_stub)
    return {
        "contact": {
            "fullName": updated.get("fullName") or "",
            "email": updated.get("email") or extracted.get("email") or "",
            "phone": updated.get("phone") or extracted.get("phone") or "",
            "yearsExperience": updated.get("yearsExperience") or extracted.get("yearsExperience") or "",
        },
        "skills": [],
        "workHistory": [],
        "accomplishmentCandidates": _heuristic_bullets(text),
        "atsKeywordSets": {"skills": [], "tools": [], "domains": [], "certifications": []},
    }


def _heuristic_bullets(text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    current_company = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("•") or stripped.startswith("-") or stripped.startswith("*"):
            bullet = stripped.lstrip("•-*· ").strip()
            if len(bullet) < 20:
                continue
            candidates.append({
                "tempId": new_id("cand_"),
                "title": bullet[:80],
                "company": current_company,
                "bullet": bullet,
                "technologies": [],
                "domains": [],
                "confidence": 0.45,
            })
        elif len(stripped) < 60 and stripped == stripped.upper():
            current_company = stripped.title()
        elif "|" in stripped and len(stripped) < 80:
            parts = [p.strip() for p in stripped.split("|")]
            if parts:
                current_company = parts[0]
    return candidates[:20]


async def run_resume_scan(
    db: Session,
    *,
    person_id: str,
    text: str = "",
    base64_data: str = "",
    mime_type: str = "",
    filename: str = "",
    use_qwen: bool = True,
    person_name: str = "",
) -> dict[str, Any]:
    resume_text = extract_text_from_upload(
        text=text,
        base64_data=base64_data,
        mime_type=mime_type,
        filename=filename,
    )
    if not resume_text.strip():
        raise ValueError("Could not extract text from resume")

    base = deterministic_scan_fields(resume_text)
    qwen_used = False
    qwen_error = ""

    if use_qwen:
        qwen_result = await extract_resume_with_qwen(db, resume_text, person_name=person_name)
        if qwen_result.get("success") and isinstance(qwen_result.get("data"), dict):
            base = _merge_scan(base, qwen_result["data"])
            qwen_used = True
        else:
            qwen_error = str(qwen_result.get("error") or "Qwen extraction failed")

    scan = save_scan(db, {
        "personId": person_id,
        "status": "complete",
        "textPreview": resume_text[:1500],
        "resumeTextLength": len(resume_text),
        "contact": base.get("contact") or {},
        "skills": base.get("skills") or [],
        "workHistory": base.get("workHistory") or [],
        "accomplishmentCandidates": base.get("accomplishmentCandidates") or [],
        "atsKeywordSets": base.get("atsKeywordSets") or {},
        "qwenUsed": qwen_used,
        "qwenError": qwen_error,
    })
    return scan


def _merge_scan(base: dict[str, Any], qwen_data: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key in ("contact", "skills", "workHistory", "accomplishmentCandidates", "atsKeywordSets"):
        qwen_val = qwen_data.get(key)
        if qwen_val:
            merged[key] = qwen_val
    if not merged.get("accomplishmentCandidates") and base.get("accomplishmentCandidates"):
        merged["accomplishmentCandidates"] = base["accomplishmentCandidates"]
    return merged


def commit_scan_accomplishments(
    db: Session,
    scan: dict[str, Any],
    *,
    candidate_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    person_id = scan.get("personId") or ""
    for candidate in scan.get("accomplishmentCandidates") or []:
        cid = str(candidate.get("tempId") or candidate.get("id") or "")
        if candidate_ids and cid not in candidate_ids:
            continue
        acc = {
            "id": new_id("acc_"),
            "personId": person_id,
            "company": candidate.get("company") or "",
            "title": candidate.get("title") or "Imported accomplishment",
            "project": candidate.get("title") or "",
            "currentBullet": candidate.get("bullet") or candidate.get("currentBullet") or "",
            "technologies": candidate.get("technologies") or [],
            "domains": candidate.get("domains") or [],
            "readiness": "draft",
            "provenance": "imported",
            "seedSource": "resume-scan",
            "scanId": scan.get("id"),
        }
        saved.append(upsert_entity(db, "accomplishment", acc))
    return saved


def load_accomplishments_for_person(db: Session, person_id: str | None = None) -> list[dict[str, Any]]:
    accs = list_entities(db, "accomplishment")
    if person_id:
        filtered = [a for a in accs if not a.get("personId") or a.get("personId") == person_id]
        if filtered:
            return filtered
    return accs
