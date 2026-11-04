"""Thin cross-cutting routes that do not belong to any one domain service.

Everything else that used to live in ``api.py`` moved into the service routers
(``resume``, ``jobs``, ``autopilot``, ``intelligence``, ``profile``,
``analytics``, ``notifications``) as part of the modular-monolith refactor. What
remains here is the dashboard root, the health check, the legacy extension full
DB sync, and the extension download/info endpoints — all genuinely
service-agnostic. Paths and behaviour are unchanged.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.db.store import import_legacy_db, legacy_db_snapshot
from analytics.dashboard import render_api_dashboard
from analytics.extension_packager import build_extension_zip, extension_info
from shared.auth_guards import require_legacy_sync_auth
from shared.deps import db_session

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def root(db: Session = Depends(db_session)) -> HTMLResponse:
    return HTMLResponse(render_api_dashboard(db))


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "career-os-api"}


# Legacy extension compatibility
@router.get("/api/db")
def get_api_db(db: Session = Depends(db_session)) -> dict[str, Any]:
    return legacy_db_snapshot(db)


@router.post("/api/db")
def upsert_api_db(
    payload: dict[str, Any],
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    require_legacy_sync_auth(request)
    import_legacy_db(db, payload)
    return {"success": True}


@router.get("/extension/info")
def get_extension_info() -> dict[str, Any]:
    return extension_info()


@router.get("/extension/download")
def download_extension(browser: str = Query(default="chrome")) -> Response:
    normalized = browser.lower().strip()
    engine = "firefox" if normalized == "firefox" else "chromium"
    try:
        payload, filename = build_extension_zip(engine)  # type: ignore[arg-type]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
