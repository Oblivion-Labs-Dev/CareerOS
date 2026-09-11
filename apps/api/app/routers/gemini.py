"""Diagnostics for the Gemini enrichment layer.

Read-only apart from two deliberate operator actions: clearing the circuit after
a configuration fix, and resetting the counters. Nothing here can start Gemini
work - this endpoint describes the layer, it does not drive it.

No key, or any part of one, is ever returned. `configured` says whether a key is
present and that is the whole of what a diagnostics reader needs to know.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services.gemini.gateway import get_gateway
from app.services.gemini.telemetry import telemetry

router = APIRouter(prefix="/gemini", tags=["gemini"])


@router.get("/status")
def status() -> dict[str, Any]:
    """One-line health, for a status pill. Cheap enough to poll."""
    gateway = get_gateway()
    circuit = gateway.breaker.snapshot()
    return {
        "success": True,
        # HEALTHY | RATE LIMITED | CIRCUIT OPEN | DISABLED
        "health": gateway.health(),
        "enabled": gateway.config.enabled,
        "configured": gateway.configured,
        "model": gateway.config.model,
        "circuitState": circuit["state"],
        "secondsUntilRetry": circuit["secondsUntilRetry"],
        "queueDepth": gateway.queue_snapshot()["depth"],
    }


@router.get("/diagnostics")
def diagnostics() -> dict[str, Any]:
    """Everything the diagnostics page shows, in one call."""
    return {"success": True, **get_gateway().diagnostics()}


@router.post("/metrics/reset")
def reset_metrics() -> dict[str, Any]:
    """Zero the counters. The circuit is untouched - that is a separate decision."""
    telemetry.reset()
    return {"success": True}


@router.post("/circuit/close")
def close_circuit() -> dict[str, Any]:
    """Close the circuit now, for when the cause was fixed rather than waited out.

    The circuit opens for a configurable cooldown precisely so that nobody has
    to do this by hand, but a 404 opens it for the longest cooldown available
    and a corrected model name should not have to wait fifteen minutes to be
    tried.
    """
    gateway = get_gateway()
    gateway.breaker.record_success()
    return {"success": True, "circuit": gateway.breaker.snapshot()}
