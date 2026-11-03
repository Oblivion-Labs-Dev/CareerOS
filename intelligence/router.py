"""FastAPI routes for the intelligence service.

Paths are kept identical to the pre-refactor routers (no service prefix is added
here); ``main.py`` includes this router without a prefix so existing
frontend/extension calls keep resolving. ``/cover-letter/generate`` was moved
verbatim out of ``apps/api/app/routers/api.py``; the intelligence signals,
Gemini diagnostics, story-map and networking sub-routers are included from their
respective modules in this package.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.store import get_kv, new_id, now_iso, upsert_entity
from intelligence.gemini_routes import router as gemini_router
from intelligence.networking_routes import router as networking_router
from intelligence.signals_routes import router as signals_router
from intelligence.story_map_routes import router as story_map_router
from shared.deps import db_session

router = APIRouter()


class CoverLetterGeneratePayload(BaseModel):
    jobId: str | None = None
    companyName: str | None = None
    roleTitle: str | None = None
    jobDescription: str | None = None
    tone: str | None = "professional"


@router.post("/cover-letter/generate")
async def generate_cover_letter(payload: CoverLetterGeneratePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    from jobs.cover_letter_pipeline import generate_cover_letter_with_review

    profile = get_kv(db, "profile") or {}
    company = payload.companyName or "the company"
    role = payload.roleTitle or profile.get("targetRole") or "the role"
    result = await generate_cover_letter_with_review(
        profile,
        company=company,
        role=role,
        job_description=payload.jobDescription or "",
        tone=payload.tone or "professional",
        use_llm=True,
    )
    letter = {
        "id": new_id("cl_"),
        "jobId": payload.jobId,
        "title": result["title"],
        "content": result["content"],
        "tone": payload.tone,
        "pipelineMode": result["pipelineMode"],
        "reviewerNotes": result["reviewerNotes"],
        "styleIssues": result["styleIssues"],
        "createdAt": now_iso(),
    }
    upsert_entity(db, "cover_letter", letter)
    return {"success": True, "coverLetter": letter}


# ── Sub-routers: /intelligence/*, /gemini/*, /story-map/*, /networking/* ───────
router.include_router(signals_router)
router.include_router(gemini_router)
router.include_router(story_map_router)
router.include_router(networking_router)
