"""Application Assistant API — aggregates the domain sub-routers into one
router with the exact same paths/behavior as the former single 2000+ line
module, so `from app.routers.application_assistant import router` keeps
working unchanged for main.py.

Split by domain for SRP: each area (settings, discovery, jobs, applications,
answers, llm, qwen, diagnostics, autopilot, llm_metrics, tailoring/receipts)
now owns its own small file instead of all 79 endpoints living in one.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    answers,
    browse_searches,
    applications,
    autopilot,
    diagnostics,
    discovery,
    jobs,
    llm,
    llm_metrics,
    qwen,
    progress,
    settings,
    tailoring_receipts,
)

router = APIRouter()
for _sub in (
    settings.router,
    discovery.router,
    jobs.router,
    applications.router,
    answers.router,
    browse_searches.router,
    llm.router,
    qwen.router,
    progress.router,
    diagnostics.router,
    autopilot.router,
    llm_metrics.router,
    tailoring_receipts.router,
):
    router.include_router(_sub)
