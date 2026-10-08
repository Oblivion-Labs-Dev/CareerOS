"""Markets API: company-first discovery for a metro area."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.store import session_scope
from app.routers.api import db_session
from app.services.markets import links, refresh, registry, views
from app.services.markets.config import Market, get_market, load_markets
from app.services.markets.importer import SeedImportError, import_seed

router = APIRouter(prefix="/markets", tags=["markets"])


class RefreshPayload(BaseModel):
    force: bool = False
    allowBrowser: bool = True


class LinkCheckPayload(BaseModel):
    force: bool = False


def _market(market_id: str) -> Market:
    market = get_market(market_id)
    if market is None:
        raise HTTPException(status_code=404, detail=f"Unknown market '{market_id}'")
    return market


def _strip(pulse: dict[str, Any], opps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one-line "what changed" banner, only when something meaningful did."""
    run = pulse.get("lastRun") or {}
    if not run:
        return None
    new_since = [o for o in opps if o.get("sinceLastScan")]
    priority_new = [o for o in new_since if (o.get("tier") or 9) <= 2]
    if priority_new:
        return {"kind": "new", "count": len(priority_new), "text": f"{len(priority_new)} high-priority opportunities appeared since your last scan"}
    if run.get("startedHiring"):
        names = run["startedHiring"]
        return {"kind": "hiring", "count": len(names), "text": f"{len(names)} tracked {'company' if len(names) == 1 else 'companies'} started hiring: {', '.join(names[:4])}"}
    if new_since:
        return {"kind": "new", "count": len(new_since), "text": f"{len(new_since)} new relevant openings since your last scan"}
    return {"kind": "none", "count": 0, "text": "No significant changes since your last scan."}


@router.get("")
def list_markets(db: Session = Depends(db_session)) -> dict[str, Any]:
    out = []
    for market in load_markets().values():
        out.append({**market.to_public(), "companies": len(registry.list_companies(db, market.id))})
    return {"markets": out}


@router.get("/{market_id}")
def market_overview(market_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    market = _market(market_id)
    if not refresh.is_running(market_id) and not links.is_running(market_id):
        links.repair_stored_urls(db, registry.list_companies(db, market_id))
    snap = views.market_snapshot(db, market)
    state = snap["state"]
    checked = links.get_links(db, market_id)
    last_run = state.get("lastRun") or {}
    new_keys: set[str] = set()
    for entry in state["companies"].values():
        if entry.get("runId") == last_run.get("runId"):
            new_keys.update(entry.get("newKeys") or [])
    for opp in snap["opportunities"]:
        opp["sinceLastScan"] = refresh.job_key(opp) in new_keys
        opp["link"] = checked.get(opp.get("url") or "")
    pulse = views.pulse(snap["companies"], snap["opportunities"], state)
    return {
        "market": market.to_public(),
        "pulse": pulse,
        "strip": _strip(pulse, snap["opportunities"]),
        "companies": snap["companies"],
        "opportunities": snap["opportunities"],
        "health": views.health_view(snap["companies"]),
        "refresh": refresh.get_progress(market_id),
        "links": links.get_progress(market_id),
        "runs": state.get("runs", [])[:5],
    }


@router.get("/{market_id}/companies/{company_id}")
def company_detail(market_id: str, company_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    market = _market(market_id)
    company = registry.get_company(db, company_id)
    if not company or market_id not in (company.get("markets") or {}):
        raise HTTPException(status_code=404, detail="Company not tracked in this market")
    state = registry.get_scan_state(db, market_id)
    opps = [o for o in views.opportunities(db, market) if o["companyId"] == company_id]
    view = views.company_view(company, market, state["companies"].get(company_id) or {}, opps, (state.get("lastRun") or {}).get("runId"))
    view["opportunities"] = opps
    view["career"]["detectionSteps"] = (company.get("career") or {}).get("detectionSteps") or []
    view["career"]["config"] = (company.get("career") or {}).get("config") or {}
    view["scan"] = state["companies"].get(company_id) or {}
    return view


@router.get("/{market_id}/health")
def market_health(market_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    market = _market(market_id)
    snap = views.market_snapshot(db, market)
    return views.health_view(snap["companies"])


@router.post("/{market_id}/import")
def import_market_seed(market_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    market = _market(market_id)
    try:
        report = import_seed(db, market)
    except SeedImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "report": report.to_dict()}


@router.get("/{market_id}/refresh")
def refresh_status(market_id: str) -> dict[str, Any]:
    _market(market_id)
    return refresh.get_progress(market_id)


@router.post("/{market_id}/refresh")
async def refresh_market(market_id: str, payload: RefreshPayload | None = None) -> dict[str, Any]:
    _market(market_id)
    body = payload or RefreshPayload()
    return refresh.start_refresh(market_id, force=body.force, allow_browser=body.allowBrowser)


@router.get("/{market_id}/links")
def link_check_status(market_id: str) -> dict[str, Any]:
    _market(market_id)
    return links.get_progress(market_id)


@router.post("/{market_id}/links/check")
async def check_market_links(market_id: str, payload: LinkCheckPayload | None = None) -> dict[str, Any]:
    _market(market_id)
    if refresh.is_running(market_id):
        raise HTTPException(status_code=409, detail="A market refresh is running; links are checked when it finishes")
    return links.start_check(market_id, force=(payload or LinkCheckPayload()).force)


@router.post("/{market_id}/companies/{company_id}/refresh")
async def refresh_company(market_id: str, company_id: str) -> dict[str, Any]:
    market = _market(market_id)
    if refresh.is_running(market_id):
        raise HTTPException(status_code=409, detail="A market refresh is running; this company will be covered by it")
    with session_scope() as db:
        company = registry.get_company(db, company_id)
    if not company or market_id not in (company.get("markets") or {}):
        raise HTTPException(status_code=404, detail="Company not tracked in this market")
    summary = await refresh.run_refresh(market.id, force=True, company_ids=[company_id])
    with session_scope() as db:
        detail = company_detail(market_id, company_id, db)
    return {"success": True, "summary": summary, "company": detail}
