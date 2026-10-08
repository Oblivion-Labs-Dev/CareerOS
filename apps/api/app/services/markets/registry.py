"""Persistence for the company registry and per-market scan cache.

Companies are `market_company` entities (one per employer, shared by every
market it appears in). Scan results are expensive to recompute, so they are
cached per market in the KV store; counts that are cheap to derive from the
canonical job store are computed at read time instead.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import get_entity, get_kv, list_entities, set_kv, upsert_entity

COMPANY_ENTITY = "market_company"


# JSON columns do not track in-place mutation: editing a loaded payload and
# saving it compares equal to the (same, mutated) committed value and nothing
# is written. Everything handed out here is a deep copy.


def list_companies(db: Session, market_id: str | None = None) -> list[dict[str, Any]]:
    companies = copy.deepcopy(list_entities(db, COMPANY_ENTITY))
    if market_id:
        companies = [
            c for c in companies
            if market_id in (c.get("markets") or {}) and not (c["markets"][market_id] or {}).get("removedFromSeedAt")
        ]
    return companies


def get_company(db: Session, company_id: str) -> dict[str, Any] | None:
    return copy.deepcopy(get_entity(db, COMPANY_ENTITY, company_id))


def save_company(db: Session, company: dict[str, Any]) -> dict[str, Any]:
    return upsert_entity(db, COMPANY_ENTITY, company)


def _scan_key(market_id: str) -> str:
    return f"markets:scan:{market_id}"


def get_scan_state(db: Session, market_id: str) -> dict[str, Any]:
    state = copy.deepcopy(get_kv(db, _scan_key(market_id)) or {})
    state.setdefault("companies", {})
    state.setdefault("runs", [])
    return state


def save_scan_state(db: Session, market_id: str, state: dict[str, Any]) -> None:
    set_kv(db, _scan_key(market_id), state)
