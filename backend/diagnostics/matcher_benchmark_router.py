"""Serve the matcher benchmark results to the web app.

Read-only over files the bench writes. It does not run experiments: those load
models and take minutes, which is not something an HTTP handler should do on a
machine with one GPU and 16GB of RAM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/matcher-benchmark", tags=["matcher-benchmark"])

DATA = Path(__file__).resolve().parents[2] / "data"

FILES = {
    "leaderboard": "matchlab_final.json",
    "ablation": "matchlab_ablation.json",
    "hybrid": "matchlab_hybrid.json",
}


def _load(name: str) -> dict[str, Any] | None:
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return None


@router.get("")
def get_matcher_benchmark() -> dict[str, Any]:
    """Everything the benchmark page needs, in one call."""
    payload: dict[str, Any] = {"available": True}
    for key, filename in FILES.items():
        payload[key] = _load(filename)
    if not payload.get("leaderboard"):
        return {
            "available": False,
            "reason": "No benchmark results yet. Run "
                      "scripts/matchlab/run.py to generate them.",
        }

    results = payload["leaderboard"].get("results") or []
    ranked = sorted(
        [r for r in results if r.get("rocAuc") is not None],
        key=lambda r: -r["rocAuc"],
    )
    if ranked:
        best = ranked[0]
        fastest = min(results, key=lambda r: r.get("latencyMs") or 1e9)
        payload["verdict"] = {
            "bestQuality": best["approach"],
            "bestQualityAuc": best["rocAuc"],
            "fastest": fastest["approach"],
            "fastestMs": fastest.get("latencyMs"),
            # The comparison that decides whether this is worth adopting.
            "rescore851Seconds": best.get("rescore851Seconds"),
        }
    return payload
