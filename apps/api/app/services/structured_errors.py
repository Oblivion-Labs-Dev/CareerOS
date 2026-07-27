from __future__ import annotations

import traceback
import uuid
from typing import Any

import httpx

from app.config import settings


def get_git_commit_sha() -> str:
    try:
        import subprocess
        from pathlib import Path

        repo = Path(__file__).resolve().parents[4]
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except OSError:
        pass
    return "unknown"


def build_structured_error(
    exc: BaseException,
    *,
    endpoint: str,
    feature: str = "scraper",
    correlation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "severity": "error",
        "service": "career-os-api",
        "environment": "local" if settings.career_os_dev_mode else "production",
        "errorType": type(exc).__name__,
        "message": str(exc),
        "stackTrace": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        "correlationId": correlation_id or str(uuid.uuid4()),
        "endpoint": endpoint,
        "gitCommitSha": get_git_commit_sha(),
        "applicationVersion": "0.1.0",
        "sourceLocation": _first_app_frame(exc),
        "feature": feature,
        "metadata": metadata or {},
        "causedBy": None,
    }


def _first_app_frame(exc: BaseException) -> str:
    tb = exc.__traceback__
    while tb is not None:
        filename = tb.tb_frame.f_code.co_filename.replace("\\", "/")
        if "site-packages" not in filename and "apps/api" in filename:
            return f"{filename}:{tb.tb_lineno}"
        tb = tb.tb_next
    return ""


def forward_to_repair_orchestrator(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not settings.career_os_repair_enabled:
        return None
    url = settings.career_os_repair_orchestrator_url.rstrip("/") + "/events"
    try:
        response = httpx.post(url, json=payload, timeout=5.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError:
        return {"success": False, "error": "repair-orchestrator-unavailable"}
