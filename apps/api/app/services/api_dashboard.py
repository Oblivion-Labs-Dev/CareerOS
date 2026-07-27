from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.db.store import get_kv, tracker_summary
from app.services.extension_packager import extension_info
from app.services.log_store import read_client_logs
from app.services.error_fix_tracker import error_fix_tracker
from app.services.repair.log_source import log_inventory

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "static" / "api-dashboard" / "index.html"


def _web_dashboard_url() -> str:
    for origin in settings.career_os_cors_origins.split(","):
        cleaned = origin.strip()
        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            return f"{cleaned.rstrip('/')}/applications"
    return "http://localhost:3000/applications"


def _profile_label(profile: dict[str, Any] | None) -> str:
    if not profile:
        return "No profile synced yet"
    full_name = str(profile.get("fullName") or "").strip()
    if full_name:
        return full_name
    first = str(profile.get("firstName") or "").strip()
    last = str(profile.get("lastName") or "").strip()
    combined = f"{first} {last}".strip()
    return combined or "Profile loaded"


def _format_ts(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%b %d, %H:%M")
    except ValueError:
        return value


def _recent_applications(applications: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    def sort_key(app: dict[str, Any]) -> str:
        return str(app.get("updatedAt") or app.get("createdAt") or "")

    return sorted(applications, key=sort_key, reverse=True)[:limit]


def _build_boot_payload(db: Session) -> dict[str, Any]:
    profile = get_kv(db, "profile") or {}
    summary = tracker_summary(db)
    applications = summary.get("applications") or []
    recent_apps = _recent_applications(applications)
    recent_logs = read_client_logs(limit=8)
    ext = extension_info()
    web_url = _web_dashboard_url()
    api_url = (settings.career_os_api_public_url or "http://localhost:8000").rstrip("/")

    return {
        "webUrl": web_url,
        "apiUrl": api_url,
        "profile": {
            "name": _profile_label(profile),
            "email": str(profile.get("email") or "—"),
        },
        "stats": {
            "applications": summary.get("applicationsCount", len(applications)),
            "jobs": summary.get("jobsCount", 0),
            "sessions": summary.get("sessionsCount", 0),
            "mappings": summary.get("mappingsCount", 0),
        },
        "recentApps": [
            {
                "company": html.escape(str(app.get("company") or "Unknown company")),
                "role": html.escape(str(app.get("role") or "Role unknown")),
                "status": html.escape(str(app.get("status") or "saved")),
                "time": _format_ts(str(app.get("updatedAt") or app.get("createdAt") or "")),
            }
            for app in recent_apps
        ],
        "recentLogs": [
            {
                "level": html.escape(str(entry.get("level") or "info")),
                "time": _format_ts(str(entry.get("ts") or "")),
                "source": html.escape(str(entry.get("source") or "client")),
                "message": html.escape(str(entry.get("message") or "")),
            }
            for entry in recent_logs
        ],
        "extension": {
            "version": str(ext.get("version") or "0.0.0"),
            "status": "Ready" if ext.get("distReady") else "Build required",
        },
        "server": {
            "devMode": settings.career_os_dev_mode,
            "refreshed": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "repairManualEnabled": settings.career_os_dev_mode,
            "repairAgentAdapter": settings.career_os_repair_agent_adapter,
        },
        "errorFix": error_fix_tracker.snapshot(),
        "logInventory": log_inventory(),
    }


def _chart_seed_from_history() -> dict[str, Any]:
    timeline = sorted(error_fix_tracker.snapshot().get("history") or [], key=lambda item: item.get("atIso") or "")
    labels: list[str] = []
    errors: list[int] = []
    fixes: list[int] = []
    error_total = 0
    fix_total = 0
    for item in timeline[-48:]:
        if item.get("kind") == "error":
            error_total += 1
        if item.get("kind") == "fix":
            fix_total += 1
        at_iso = str(item.get("atIso") or "")
        try:
            parsed = datetime.fromisoformat(at_iso.replace("Z", "+00:00"))
            label = parsed.astimezone().strftime("%H:%M")
        except ValueError:
            label = at_iso[:16] or "—"
        labels.append(label)
        errors.append(error_total)
        fixes.append(fix_total)
    return {"labels": labels, "errors": errors, "fixes": fixes}


def _latest_repair_run() -> dict[str, Any] | None:
    try:
        from app.services.repair.processor import latest_manual_run

        return latest_manual_run()
    except Exception:
        return None


def _build_boot_payload_with_repair(db: Session) -> dict[str, Any]:
    payload = _build_boot_payload(db)
    payload["repairRun"] = _latest_repair_run()
    payload["chartSeed"] = _chart_seed_from_history()
    return payload


def render_api_dashboard(db: Session) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    boot_json = json.dumps(_build_boot_payload_with_repair(db), ensure_ascii=False)
    html = template.replace("__BOOT_JSON__", boot_json)
    if settings.career_os_dev_mode:
        html = html.replace('id="repair-manual-panel" aria-label="Manual log repair" hidden', 'id="repair-manual-panel" aria-label="Manual log repair"')
    return html
