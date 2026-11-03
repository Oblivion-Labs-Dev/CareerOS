"""FastAPI routes for the autopilot service.

Paths are kept identical to the pre-refactor routers (no service prefix is added
here); ``main.py`` includes this router without a prefix so existing
frontend/extension calls keep resolving. The applications/autofill/questions/
benchmarks/referrals handlers were moved verbatim out of
``apps/api/app/routers/api.py``; the Application Assistant sub-routers (the whole
``/application-assistant/*`` surface) plus the matcher-benchmark and dev
repair/demo routers are included from this package.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db.store import (
    EntityStore,
    list_entities,
    new_id,
    now_iso,
    patch_entity,
    set_kv,
    tracker_summary,  # noqa: F401  (kept import parity; tracker summary lives in notifications)
    upsert_entity,
)
from autopilot.application_assistant import router as application_assistant_router
from autopilot.matcher_benchmark_routes import router as matcher_benchmark_router
from autopilot.repair_demo_routes import router as repair_demo_router
from autopilot.repair_manual_routes import router as repair_manual_router
from intelligence.answer_engine import generate_answer, load_custom_answers
from shared.deps import db_session

router = APIRouter()


class ApplicationPayload(BaseModel):
    application: dict[str, Any]


class ApplicationPatchPayload(BaseModel):
    patch: dict[str, Any]


class FieldMappingPayload(BaseModel):
    mapping: dict[str, Any]


class QuestionAnswerPayload(BaseModel):
    question: str
    context: dict[str, Any] | None = None


class ReferralPayload(BaseModel):
    referral: dict[str, Any]


class ReferralPatchPayload(BaseModel):
    patch: dict[str, Any]


class ReferralAskMessagePayload(BaseModel):
    message: str


class TestResolveRequest(BaseModel):
    question: str
    options: list[str] = Field(default_factory=list)
    fieldId: str = "test_field"
    profile: dict[str, Any] = Field(default_factory=dict)
    model: str = "qwen2.5:3b"


DEFAULT_REFERRAL_ASK_MESSAGE = """I hope you're doing well! I came across a job that aligns closely with my background and was wondering if you'd be open to referring me. I have 7+ years of experience at Microsoft and Amazon building distributed systems, AI infrastructure, and cloud-native platforms, and I've recently been focused on agentic AI and developer tooling.

I believe my experience is a strong match for the role. If you're comfortable referring me, I'd really appreciate it. I've attached the job link and my resume for context. Thanks for taking the time to consider my request!"""


@router.post("/applications")
def create_application(payload: ApplicationPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    saved = upsert_entity(db, "application", payload.application)
    return {"success": True, "application": saved}


@router.get("/applications")
def list_applications(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"applications": list_entities(db, "application")}


@router.get("/applications/export.csv")
def export_applications(db: Session = Depends(db_session)):
    from fastapi.responses import Response
    from notifications.tracker import pipeline as tracker_pipeline

    csv_text = tracker_pipeline.export_applications_csv(db)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=careeros-applications.csv"},
    )


@router.post("/applications/import")
async def import_applications(file: UploadFile = File(...), db: Session = Depends(db_session)) -> dict[str, Any]:
    from notifications.tracker import pipeline as tracker_pipeline

    raw = await file.read()
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")
    result = tracker_pipeline.import_applications_csv(db, content)
    return {"success": True, **result}


@router.patch("/applications/{application_id}")
def update_application(
    application_id: str,
    payload: ApplicationPatchPayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    updated = patch_entity(db, "application", application_id, payload.patch)
    if not updated:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"success": True, "application": updated}


@router.post("/autofill/map-field")
def map_field(payload: FieldMappingPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    mapping = upsert_entity(
        db,
        "field_mapping",
        {
            **payload.mapping,
            "id": payload.mapping.get("id") or new_id("map_"),
            "lastUsedAt": now_iso(),
        },
    )
    return {"success": True, "mapping": mapping}


@router.get("/autofill/mappings")
def list_mappings(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"mappings": list_entities(db, "field_mapping")}


@router.post("/questions/answer")
def answer_question(payload: QuestionAnswerPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.db.store import get_kv

    learned = list_entities(db, "learned_answer")
    normalized = payload.question.strip().lower()
    for item in learned:
        if item.get("question", "").strip().lower() == normalized:
            return {"success": True, "answer": item.get("answer"), "source": "learned"}
    profile = get_kv(db, "profile") or {}
    context = payload.context or {}
    company = str(context.get("companyName") or context.get("company") or "")
    role = str(context.get("roleTitle") or context.get("role") or profile.get("targetRole") or "")
    engine_answer = generate_answer(payload.question, company=company, role_title=role, profile=profile)
    if engine_answer:
        return {"success": True, "answer": engine_answer, "source": "answer_engine"}
    fallback = (
        f"Based on my experience as {profile.get('currentTitle', 'a professional')}, "
        f"I would approach this thoughtfully and align with {profile.get('targetRole', 'the role')} expectations."
    )
    return {"success": True, "answer": fallback, "source": "generated"}


@router.get("/questions/answer-bank")
def get_answer_bank() -> dict[str, Any]:
    return {"success": True, "answers": load_custom_answers()}


@router.get("/referrals")
def list_referrals(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"referrals": list_entities(db, "referral")}


@router.get("/referrals/ask-message")
def get_referral_ask_message(db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.db.store import get_kv

    stored = get_kv(db, "referral_ask_message")
    message = stored if isinstance(stored, str) and stored.strip() else DEFAULT_REFERRAL_ASK_MESSAGE
    return {"message": message}


@router.put("/referrals/ask-message")
def save_referral_ask_message(
    payload: ReferralAskMessagePayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    set_kv(db, "referral_ask_message", message)
    return {"success": True, "message": message}


@router.post("/referrals")
def create_referral(payload: ReferralPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    saved = upsert_entity(
        db,
        "referral",
        {
            **payload.referral,
            "id": payload.referral.get("id") or new_id("ref_"),
            "status": payload.referral.get("status") or "active",
        },
    )
    return {"success": True, "referral": saved}


@router.patch("/referrals/{referral_id}")
def update_referral(
    referral_id: str,
    payload: ReferralPatchPayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    updated = patch_entity(db, "referral", referral_id, payload.patch)
    if not updated:
        raise HTTPException(status_code=404, detail="Referral contact not found")
    return {"success": True, "referral": updated}


@router.delete("/referrals/{referral_id}")
def delete_referral(referral_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    row = (
        db.query(EntityStore)
        .filter(EntityStore.entity_type == "referral", EntityStore.id == referral_id)
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Referral contact not found")
    db.delete(row)
    return {"success": True}


@router.get("/benchmarks")
async def get_benchmarks_route() -> dict[str, Any]:
    """Retrieve saved LLM benchmark results."""
    # The results file lives in apps/api/data (unchanged by the refactor);
    # resolve it from the repo root rather than this module's new location.
    bench_file = Path(__file__).resolve().parents[1] / "apps" / "api" / "data" / "benchmark_results.json"
    if bench_file.exists():
        try:
            return json.loads(bench_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"leaderboard": [], "recommendation": {}, "totalTestCases": 0}


@router.post("/benchmarks/run")
async def run_benchmarks_route() -> dict[str, Any]:
    """Execute full sequential benchmark comparing Ollama local models and Gemini API."""
    from autopilot import llm_client
    from autopilot.benchmark_suite import run_full_sequential_benchmark

    if not llm_client.LOCAL_LLM_ENABLED:
        raise HTTPException(status_code=409, detail="Local LLMs are switched off (CAREEROS_LOCAL_LLM=off).")
    gemini_key = os.environ.get("GEMINI_API_KEY", settings.gemini_api_key)
    results = await run_full_sequential_benchmark(
        gemini_api_key=gemini_key,
        output_path="data/benchmark_results.json",
    )
    return results


@router.post("/benchmarks/test-resolve")
async def test_resolve_field_route(payload: TestResolveRequest) -> dict[str, Any]:
    """Test resolution of a specific question variation with rule resolver and model resolution."""
    import time
    from autopilot.benchmark_dataset import BENCHMARK_PROFILE, BENCHMARK_RESUME_TEXT
    # The resolver is `resolve_answer`; this route still imported a name it had
    # before a rename, so every call returned 500 rather than a resolution.
    from autopilot.profile_answer_resolver import resolve_answer
    from autopilot.question_classifier import classify_question, QuestionType
    from autopilot.cross_field_validator import validate_answers
    from autopilot.submission_policy import SubmissionPolicy

    active_profile = payload.profile if payload.profile else BENCHMARK_PROFILE
    start_t = time.perf_counter()

    # 1. Deterministic Rule Classifier & Resolver
    qtype = classify_question(payload.question)
    resolution = resolve_answer(
        field_id=payload.fieldId,
        question_text=payload.question,
        profile=active_profile,
        options=payload.options,
    )

    # 2. Cross-field validation & risk-based policy check
    val_report = validate_answers([resolution], active_profile)
    policy_res = SubmissionPolicy.evaluate([resolution], val_report, profile=active_profile)

    latency_ms = int((time.perf_counter() - start_t) * 1000)

    return {
        "success": True,
        "question": payload.question,
        "questionType": qtype.value,
        "resolutionMethod": resolution.resolution_method,
        "resolvedAnswer": resolution.answer,
        "confidence": resolution.confidence,
        "sourceKey": resolution.profile_key,
        "sourceValue": resolution.source_value,
        "validationStatus": val_report.status,
        "policyDecision": policy_res.decision.value,
        "riskTier": policy_res.risk_tier.value,
        "canAutoSubmit": policy_res.can_auto_submit,
        "blockingIssues": policy_res.blocking_issues,
        "warnings": policy_res.warnings,
        "latencyMs": latency_ms,
    }


# ── Sub-routers: /application-assistant/*, /matcher-benchmark, /dev/* ──────────
router.include_router(application_assistant_router)
router.include_router(matcher_benchmark_router)
router.include_router(repair_demo_router)
router.include_router(repair_manual_router)
