"""Daily/weekly task checklist — Intelligence Layer CIOS rituals."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import get_kv, set_kv

KV_KEY = "intelligence_tasks"

DAILY_TASKS = [
    {"key": "outreach_5", "label": "5 hyper-personal outreach messages to alumni / hiring managers"},
    {"key": "strategy_memo", "label": "Write or refine one strategy memo — send to a real person"},
    {"key": "apply_5", "label": "Apply to 5 roles with a tailored resume"},
    {"key": "follow_ups", "label": "Follow up with people who have not replied"},
    {"key": "pm_concept", "label": "Learn one PM or role concept"},
]

WEEKLY_TASKS = [
    {"key": "linkedin_post", "label": "Post one article on LinkedIn"},
    {"key": "cios_review", "label": "Run CIOS review — double down on what got replies"},
    {"key": "case_study", "label": "Add one case study to your portfolio"},
    {"key": "book_read", "label": "Make progress on professional reading"},
    {"key": "resume_update", "label": "Update resume based on feedback"},
]


def _today() -> str:
    return date.today().isoformat()


def _week_start() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


def _load_log(db: Session) -> dict[str, Any]:
    return get_kv(db, KV_KEY) or {"daily": {}, "weekly": {}, "artifacts": []}


def _save_log(db: Session, payload: dict[str, Any]) -> None:
    set_kv(db, KV_KEY, payload)


def get_today(db: Session) -> dict[str, Any]:
    log = _load_log(db)
    day_key = _today()
    day_log = log.get("daily", {}).get(day_key, {})
    items = [{**task, "done": bool(day_log.get(task["key"], {}).get("done")), "notes": day_log.get(task["key"], {}).get("notes", "")} for task in DAILY_TASKS]
    return {"date": day_key, "tasks": items, "funnel": log.get("funnel", {})}


def get_week(db: Session) -> dict[str, Any]:
    log = _load_log(db)
    week_key = _week_start()
    week_log = log.get("weekly", {}).get(week_key, {})
    items = [{**task, "done": bool(week_log.get(task["key"], {}).get("done")), "notes": week_log.get(task["key"], {}).get("notes", "")} for task in WEEKLY_TASKS]
    return {"weekStart": week_key, "tasks": items}


def tick_task(db: Session, *, period: str, key: str, done: bool, notes: str = "") -> dict[str, Any]:
    log = _load_log(db)
    bucket = "daily" if period == "daily" else "weekly"
    period_key = _today() if period == "daily" else _week_start()
    log.setdefault(bucket, {}).setdefault(period_key, {})
    log[bucket][period_key][key] = {"done": done, "notes": notes}
    _save_log(db, log)
    return {"success": True, "period": period, "key": key, "done": done}


def list_artifacts(db: Session) -> list[dict[str, Any]]:
    return list(_load_log(db).get("artifacts") or [])


def add_artifact(db: Session, artifact: dict[str, Any]) -> dict[str, Any]:
    log = _load_log(db)
    items = list(log.get("artifacts") or [])
    items.insert(0, artifact)
    log["artifacts"] = items[:50]
    _save_log(db, log)
    return artifact
