"""Request-level authorization guards shared across service routers.

These are small FastAPI dependencies that gate sensitive endpoints when the
app is not in local dev mode. They were defined inline in routers/api.py; they
live here so every service router (api.py, notifications, autopilot, …) shares
one definition instead of duplicating the policy.

``shared`` holds cross-cutting contracts only — these guards are exactly that
(a uniform auth policy), with no business logic.
"""

from fastapi import HTTPException, Request

from app.config import settings


def require_legacy_sync_auth(request: Request) -> None:
    """Guard full DB overwrite when not in local dev mode."""
    if settings.career_os_dev_mode:
        return
    if not settings.career_os_api_key:
        raise HTTPException(status_code=503, detail="Legacy sync is disabled until CAREER_OS_API_KEY is set")
    provided = request.headers.get("x-career-os-api-key", "")
    if provided != settings.career_os_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


def require_protected_action_auth(request: Request) -> None:
    """Guard sensitive write actions when not in local dev mode."""
    if settings.career_os_dev_mode:
        return
    if not settings.career_os_api_key:
        raise HTTPException(status_code=503, detail="Action disabled until CAREER_OS_API_KEY is set")
    provided = request.headers.get("x-career-os-api-key", "")
    if provided != settings.career_os_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


def require_gmail_configured() -> tuple[str, str]:
    if not settings.gmail_user or not settings.gmail_app_password:
        raise HTTPException(
            status_code=503,
            detail="Gmail is not configured. Set GMAIL_USER and GMAIL_APP_PASSWORD in apps/api/.env",
        )
    return settings.gmail_user, settings.gmail_app_password
