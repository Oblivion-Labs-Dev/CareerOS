"""Social hiring signals — Intelligence Layer (KV-backed stub until Apify worker wired)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.store import get_kv, set_kv

KV_KEY = "intelligence_signals"


def _load(db: Session) -> dict[str, Any]:
    return get_kv(db, KV_KEY) or {"signals": [], "contacts": [], "lastScan": None}


def list_signals(db: Session, *, min_intent: int = 50, page: int = 1, per_page: int = 30) -> dict[str, Any]:
    payload = _load(db)
    signals = [s for s in payload.get("signals") or [] if int(s.get("hiring_intent") or 0) >= min_intent]
    total = len(signals)
    start = (page - 1) * per_page
    page_items = signals[start : start + per_page]
    return {
        "signals": page_items,
        "total": total,
        "page": page,
        "perPage": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
        "lastScan": payload.get("lastScan"),
    }


def get_stats(db: Session) -> dict[str, Any]:
    payload = _load(db)
    signals = payload.get("signals") or []
    return {
        "total": len(signals),
        "highIntent": sum(1 for s in signals if int(s.get("hiring_intent") or 0) >= 75),
        "contacts": len(payload.get("contacts") or []),
        "lastScan": payload.get("lastScan"),
    }


def trigger_scan(db: Session) -> dict[str, Any]:
    """Placeholder — wire Apify LinkedIn posts scraper when APIFY_TOKEN is set."""
    payload = _load(db)
    return {
        "status": "pending",
        "message": "Signal scan requires APIFY_TOKEN. Configure in apps/api/.env to enable LinkedIn hiring-post detection.",
        "lastScan": payload.get("lastScan"),
    }


def list_contacts(db: Session) -> dict[str, Any]:
    payload = _load(db)
    contacts = payload.get("contacts") or []
    return {"contacts": contacts, "total": len(contacts)}
