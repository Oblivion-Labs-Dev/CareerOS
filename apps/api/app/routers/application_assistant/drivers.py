"""Application-driver registry endpoints (preparation-only).

No endpoint here can submit an application. The existing autopilot endpoints
(CAREEROS_LIVE_APPLY + approved job IDs + review gates) remain the sole
submission path.
"""

from __future__ import annotations

import time
from typing import Any

from ._common import *  # noqa: F401,F403
from ._common import APIRouter, Depends
from app.db.store import get_kv, list_entities
from app.services.application_assistant.drivers import (
    claim_is_reusable,
    detect_platform,
    driver_summary,
    find_claim,
    get_driver,
    list_drivers,
    preparation_idempotency_key,
    record_claim,
    record_metric,
)
from app.services.application_assistant.drivers.base import ApplicationMode

router = APIRouter(prefix="/application-assistant", tags=["application-assistant"])

ALL_PLATFORMS = [d.platform for d in list_drivers()]


class DriverPreparePayload(BaseModel):
    job: dict[str, Any] = Field(default_factory=dict)
    formHtml: str | None = None


@router.get("/drivers")
def list_drivers_endpoint(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"drivers": driver_summary(db)}


@router.get("/drivers/{platform}/capabilities")
def driver_capabilities(platform: str) -> dict[str, Any]:
    driver = get_driver(platform)
    if driver is None:
        return {"error": f"unknown driver platform: {platform}", "platforms": ALL_PLATFORMS}
    caps = driver.capabilities
    return {
        "platform": driver.platform,
        "displayName": driver.display_name,
        "capabilities": caps.supported_operations(),
        "unsupportedCapabilities": caps.unsupported_operations(),
    }


@router.post("/drivers/prepare")
def prepare_application(
    payload: DriverPreparePayload, db: Session = Depends(db_session)
) -> dict[str, Any]:
    """Detect the ATS, discover questions, map the profile. Never submits."""

    job = payload.job or {}
    apply_url = job.get("applyUrl") or job.get("applicationUrl") or job.get("url") or ""
    driver = detect_platform(str(apply_url)) or get_driver("generic")
    assert driver is not None
    started = time.perf_counter()

    key = preparation_idempotency_key(driver.platform, job)
    existing = find_claim(db, key)
    if existing is not None and claim_is_reusable(existing):
        record_metric(
            db, driver=driver.platform, op="prepare", outcome="reused", detail=key
        )
        return {
            "reused": True,
            "idempotencyKey": key,
            "claim": existing,
            "mode": ApplicationMode.REVIEW.value,
            "platform": driver.platform,
        }

    try:
        approved_answers = _load_approved_answers(db)
        prepared = driver.prepare(
            job,
            _load_profile(db),
            form_html=payload.formHtml,
            approved_answers=approved_answers,
        )
        claim = record_claim(db, key=key, platform=driver.platform, job=job)
    except Exception as exc:
        record_metric(
            db,
            driver=driver.platform,
            op="prepare",
            outcome="error",
            detail=str(exc),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return {"error": f"preparation failed: {exc}", "platform": driver.platform}

    latency = int((time.perf_counter() - started) * 1000)
    record_metric(
        db,
        driver=driver.platform,
        op="prepare",
        outcome="ok",
        detail=prepared.mode.value,
        latency_ms=latency,
    )
    record_metric(db, driver=driver.platform, op="route", outcome=prepared.mode.value)
    result = prepared.to_dict()
    result["reused"] = False
    result["idempotencyKey"] = key
    result["claim"] = claim
    return result


def _load_profile(db: Session) -> dict[str, Any]:
    profile = get_kv(db, "profile") or {}
    return profile if isinstance(profile, dict) else {}


def _load_approved_answers(db: Session) -> dict[str, str]:
    try:
        rows = list_entities(db, "aa_answer_library")
    except Exception:
        return {}
    approved: dict[str, str] = {}
    for row in rows:
        if str(row.get("status") or "approved").lower() not in ("approved", "verified"):
            continue
        question = str(row.get("question") or row.get("label") or "")
        answer = str(row.get("answer") or row.get("value") or "")
        if question and answer:
            approved[question] = answer
    return approved
