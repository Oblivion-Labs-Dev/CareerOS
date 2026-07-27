from __future__ import annotations

import traceback

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.config import settings
from app.services.log_store import append_client_log

router = APIRouter(prefix="/dev/demo", tags=["dev-demo"])


class DemoScraperFailure(RuntimeError):
    """Intentional demo exception for manual repair POC."""


@router.get("/unhandled-scraper-error")
def trigger_demo_scraper_error() -> dict:
    """Record a backend error locally. Processing happens only via manual dashboard action."""
    if not settings.career_os_dev_mode:
        raise HTTPException(status_code=404, detail="Not found")

    message = "Simulated scraper profile fetch failure for repair pipeline demo"
    stack_trace = "".join(traceback.format_exc()) if False else (
        'File "apps/api/app/routers/repair_demo.py", line 28, in trigger_demo_scraper_error\n'
        f"DemoScraperFailure: {message}\n"
    )

    append_client_log(
        {
            "level": "error",
            "source": "api-backend",
            "module": "scraper",
            "message": message,
            "metadata": {
                "demo": True,
                "operation": "profile_scrape",
                "endpoint": "GET /dev/demo/unhandled-scraper-error",
                "errorType": "DemoScraperFailure",
                "stackTrace": stack_trace,
            },
        }
    )

    return JSONResponse(
        status_code=200,
        content={
            "success": False,
            "demo": True,
            "message": "Demo backend error recorded locally. Click Process Logs & Errors on the API dashboard.",
            "endpoint": "GET /dev/demo/unhandled-scraper-error",
        },
    )
