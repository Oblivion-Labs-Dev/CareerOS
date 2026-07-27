"""Auto Apply settings and log — Intelligence Layer (CareerOS KV)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import get_kv, set_kv

SETTINGS_KEY = "intelligence_auto_apply_settings"
LOG_KEY = "intelligence_auto_apply_log"

DEFAULT_SETTINGS = {
    "enabled": False,
    "max_per_run": 5,
    "enabled_roles": "pm,tpm,product,swe,ux",
    "dry_run_default": True,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_settings(db: Session) -> dict[str, Any]:
    return {**DEFAULT_SETTINGS, **(get_kv(db, SETTINGS_KEY) or {})}


def update_settings(db: Session, patch: dict[str, Any]) -> dict[str, Any]:
    current = get_settings(db)
    current.update({k: v for k, v in patch.items() if v is not None})
    set_kv(db, SETTINGS_KEY, current)
    return current


def get_log(db: Session, *, limit: int = 50) -> list[dict[str, Any]]:
    return list(get_kv(db, LOG_KEY) or [])[:limit]


def append_log(db: Session, entry: dict[str, Any]) -> dict[str, Any]:
    items = list(get_kv(db, LOG_KEY) or [])
    record = {**entry, "at": _utc_now()}
    items.insert(0, record)
    set_kv(db, LOG_KEY, items[:100])
    return record


def run_auto_apply(db: Session, *, dry_run: bool = True) -> dict[str, Any]:
    settings = get_settings(db)
    if not settings.get("enabled") and not dry_run:
        return {"success": False, "message": "Auto Apply is disabled. Enable in settings first."}
    message = "Dry run preview — programmatic ATS submission requires browser extension integration."
    entry = append_log(db, {"action": "dry_run" if dry_run else "run", "message": message, "count": 0})
    return {"success": True, "dryRun": dry_run, "message": message, "logEntry": entry}
