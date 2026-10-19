"""Persistent idempotency for application preparation.

Duplicate-prevention rule: preparing the same (platform, company, requisition,
resume) twice must never create two independent application pipelines. A
deterministic key is stored as an ``aa_preparation_claim`` entity; subsequent
preparations return the original claim and are counted as "reused".

Note: the existing autopilot stack already gates live submissions with
``aa_application_claim`` + submission receipts; this layer protects the
*preparation* side (never blind-retries, never double-prefills).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

CLAIM_ENTITY = "aa_preparation_claim"


def preparation_idempotency_key(
    platform: str,
    job: dict[str, Any],
    resume_fingerprint: str = "",
) -> str:
    parts = [
        (platform or "").lower(),
        str(job.get("companyName") or job.get("company") or "").strip().lower(),
        str(
            job.get("externalId")
            or job.get("greenhouse_id")
            or job.get("requisition_id")
            or ""
        ).strip(),
        str(job.get("applyUrl") or job.get("applicationUrl") or job.get("url") or "").strip().lower(),
        str(job.get("title") or "").strip().lower(),
        resume_fingerprint,
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return digest


def find_claim(db: Any, key: str) -> dict[str, Any] | None:
    from app.db.store import list_entities_by_json_equals

    rows = list_entities_by_json_equals(db, CLAIM_ENTITY, "$.idempotencyKey", key)
    return rows[0] if rows else None


def record_claim(db: Any, *, key: str, platform: str, job: dict[str, Any]) -> dict[str, Any]:
    from app.db.store import now_iso, upsert_entity

    payload = {
        "id": key,
        "idempotencyKey": key,
        "platform": platform,
        "company": job.get("companyName") or job.get("company") or "",
        "title": job.get("title") or "",
        "jobUrl": job.get("applyUrl") or job.get("applicationUrl") or job.get("url") or "",
        "createdAt": now_iso(),
    }
    return upsert_entity(db, CLAIM_ENTITY, payload)


def claim_is_reusable(claim: dict[str, Any], max_age_hours: float = 72.0) -> bool:
    """Claims stay reusable until the job materially changes or they expire."""

    if not claim:
        return False
    created = str(claim.get("createdAt") or "")
    if not created:
        return False
    try:
        from datetime import datetime, timedelta

        created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
        age = datetime.utcnow().replace(tzinfo=created_at.tzinfo) - created_at
        return age <= timedelta(hours=max_age_hours)
    except Exception:
        return False
