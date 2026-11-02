"""Autopilot API — aggregates all autopilot sub-routers."""
from __future__ import annotations
from fastapi import APIRouter
from . import (
    answers, browse_searches, applications, autopilot, diagnostics,
    discovery, jobs, llm, llm_metrics, qwen, progress, settings, tailoring_receipts,
)
router = APIRouter()
for _sub in (
    settings.router, discovery.router, jobs.router, applications.router,
    answers.router, browse_searches.router, llm.router, qwen.router,
    progress.router, diagnostics.router, autopilot.router,
    llm_metrics.router, tailoring_receipts.router,
):
    router.include_router(_sub)
