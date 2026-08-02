"""Night Shift — Tier-2 auto-fill queue (Intelligence Layer, CareerOS KV + job discover)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import get_kv, list_entities, set_kv
from app.services.intelligence.night_shift_config import TIER_1_COMPANIES, TIER_2_COMPANIES, night_shift_eligible
from app.services.job_discover import role_classifier
from app.services.job_discover import store as job_store

SETTINGS_KEY = "intelligence_night_shift_settings"
QUEUE_KEY = "intelligence_night_shift_queue"

DEFAULT_SETTINGS = {
    "enabled": False,
    "max_per_night": 20,
    "min_fit_score": 50,
    "enabled_roles": "pm,tpm,product",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _company_key(name: str) -> str:
    n = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    return re.sub(r"\d+$", "", n)


def get_settings(db: Session) -> dict[str, Any]:
    return {**DEFAULT_SETTINGS, **(get_kv(db, SETTINGS_KEY) or {})}


def update_settings(db: Session, patch: dict[str, Any]) -> dict[str, Any]:
    current = get_settings(db)
    current.update({k: v for k, v in patch.items() if v is not None})
    set_kv(db, SETTINGS_KEY, current)
    return current


def _load_queue(db: Session) -> list[dict[str, Any]]:
    return list(get_kv(db, QUEUE_KEY) or [])


def _save_queue(db: Session, items: list[dict[str, Any]]) -> None:
    set_kv(db, QUEUE_KEY, items)


def get_queue(db: Session, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    items = _load_queue(db)
    if status:
        items = [item for item in items if item.get("status") == status]
    return items[:limit]


def update_queue_item(db: Session, item_id: str, patch: dict[str, Any]) -> bool:
    items = _load_queue(db)
    for item in items:
        if item.get("id") == item_id:
            item.update(patch)
            item["updatedAt"] = _utc_now()
            _save_queue(db, items)
            return True
    return False


def get_tiers() -> dict[str, Any]:
    return {
        "tier_1_never_apply": sorted(TIER_1_COMPANIES.keys()),
        "tier_2_eligible": TIER_2_COMPANIES,
        "tier_1_count": len(TIER_1_COMPANIES),
        "tier_2_count": len(TIER_2_COMPANIES),
    }


def select_for_night_shift(db: Session, *, dry_run: bool = False) -> dict[str, Any]:
    settings = get_settings(db)
    if not settings.get("enabled"):
        return {"success": True, "enabled": False, "queued": 0, "message": "Night Shift is OFF. Enable the toggle to run."}

    profile = get_kv(db, "profile") or {}
    if not (profile.get("firstName") or profile.get("first_name")) or not profile.get("email"):
        return {"success": False, "queued": 0, "error": "Profile incomplete — need name and email before Night Shift."}

    cap = int(settings.get("max_per_night") or 20)
    min_fit = int(settings.get("min_fit_score") or 0)
    allowed_roles = {part.strip() for part in str(settings.get("enabled_roles") or "pm,tpm,product").split(",") if part.strip()}

    applications = list_entities(db, "application")
    applied_urls = {str(a.get("url") or "") for a in applications}
    queue = _load_queue(db)
    queued_job_ids = {item.get("jobId") for item in queue}
    seen_companies = {_company_key(item.get("companyName") or "") for item in queue if item.get("companyName")}

    snapshot = job_store.get_snapshot(db)
    candidates = [
        job
        for job in snapshot.get("jobs") or []
        if (job.get("relevancyScore") or 0) >= min_fit
        and job.get("id") not in queued_job_ids
        and str(job.get("url") or "") not in applied_urls
    ]
    candidates.sort(key=lambda job: job.get("relevancyScore") or 0, reverse=True)

    selected: list[dict[str, Any]] = []
    blocked_tier1 = 0
    skipped_not_tier2 = 0
    skipped_role = 0

    for job in candidates:
        company = job.get("companyName") or ""
        title = job.get("title") or ""
        eligible, reason = night_shift_eligible(company)
        if not eligible:
            if reason == "tier_1_blocked":
                blocked_tier1 += 1
            else:
                skipped_not_tier2 += 1
            continue

        role = role_classifier.classify_role(title)
        if role is None or role not in allowed_roles:
            skipped_role += 1
            continue

        ckey = _company_key(company)
        if ckey in seen_companies:
            continue
        seen_companies.add(ckey)

        item = {
            "id": f"ns_{job.get('id')}",
            "jobId": job.get("id"),
            "companyName": company,
            "title": title,
            "url": job.get("url"),
            "location": job.get("location"),
            "relevancyScore": job.get("relevancyScore"),
            "roleTag": role_classifier.get_resume_tag_for_role(role),
            "status": "queued",
            "createdAt": _utc_now(),
        }
        selected.append(item)
        if len(selected) >= cap:
            break

    if not dry_run and selected:
        merged = selected + queue
        _save_queue(db, merged)

    return {
        "success": True,
        "enabled": True,
        "dryRun": dry_run,
        "queued": len(selected),
        "selected": selected,
        "blockedTier1": blocked_tier1,
        "skippedNotTier2": skipped_not_tier2,
        "skippedRole": skipped_role,
    }
