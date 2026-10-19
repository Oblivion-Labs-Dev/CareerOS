"""Driver registry — lookup, detection, and per-driver metrics."""

from __future__ import annotations

from typing import Any

from .base import ApplicationDriver
from .platforms import (
    AshbyDriver,
    GenericDriver,
    GreenhouseDriver,
    IcimsDriver,
    LeverDriver,
    OracleDriver,
    PersonioDriver,
    RecruiteeDriver,
    SmartRecruitersDriver,
    WorkableDriver,
    WorkdayDriver,
)

_REGISTRY: dict[str, ApplicationDriver] = {}
for _driver in (
    GreenhouseDriver(),
    AshbyDriver(),
    LeverDriver(),
    WorkableDriver(),
    SmartRecruitersDriver(),
    WorkdayDriver(),
    IcimsDriver(),
    OracleDriver(),
    PersonioDriver(),
    RecruiteeDriver(),
    GenericDriver(),
):
    _REGISTRY[_driver.platform] = _driver


def list_drivers() -> list[ApplicationDriver]:
    ordered = ["greenhouse", "ashby", "lever", "workable", "smartrecruiters",
               "workday", "icims", "oracle", "personio", "recruitee", "generic"]
    return [_REGISTRY[p] for p in ordered if p in _REGISTRY]


def get_driver(platform: str) -> ApplicationDriver | None:
    return _REGISTRY.get((platform or "").lower())


def detect_platform(url: str) -> ApplicationDriver | None:
    """Return the first driver whose host patterns match the URL."""

    if not url:
        return None
    for driver in list_drivers():
        if driver.platform == "generic":
            continue
        if driver.detect(url):
            return driver
    return None


def driver_summary(db: Any | None = None) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    metrics = _metrics_by_driver(db) if db is not None else {}
    for driver in list_drivers():
        caps = driver.capabilities
        summaries.append(
            {
                "platform": driver.platform,
                "displayName": driver.display_name,
                "capabilities": caps.supported_operations(),
                "unsupportedCapabilities": caps.unsupported_operations(),
                "metrics": metrics.get(driver.platform, {}),
            }
        )
    return summaries


# ---------------------------------------------------------------------------
# Metrics (persisted per-driver op outcomes)
# ---------------------------------------------------------------------------


def _metrics_by_driver(db: Any) -> dict[str, dict[str, Any]]:
    from app.db.store import list_entities

    try:
        rows = list_entities(db, "aa_driver_metric")
    except Exception:
        return {}
    aggregated: dict[str, dict[str, Any]] = {}
    for row in rows:
        driver = str(row.get("driver") or "unknown")
        bucket = aggregated.setdefault(
            driver,
            {"preparations": 0, "reused": 0, "reviewRouted": 0, "manualRouted": 0},
        )
        op = str(row.get("op") or "")
        outcome = str(row.get("outcome") or "")
        if op == "prepare" and outcome == "ok":
            bucket["preparations"] += 1
        if op == "prepare" and outcome == "reused":
            bucket["reused"] += 1
        if op == "route" and outcome == "REVIEW":
            bucket["reviewRouted"] += 1
        if op == "route" and outcome == "MANUAL":
            bucket["manualRouted"] += 1
    return aggregated


def record_metric(
    db: Any,
    *,
    driver: str,
    op: str,
    outcome: str,
    detail: str = "",
    latency_ms: int = 0,
) -> None:
    """Persist one per-driver metric row (best-effort; never raises)."""

    try:
        from app.db.store import new_id, now_iso, upsert_entity

        upsert_entity(
            db,
            "aa_driver_metric",
            {
                "id": new_id("drv_"),
                "driver": driver,
                "op": op,
                "outcome": outcome,
                "detail": detail[:500],
                "latencyMs": latency_ms,
                "at": now_iso(),
            },
        )
    except Exception:
        pass
