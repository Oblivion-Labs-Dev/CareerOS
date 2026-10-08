"""Requirement weights shared by the planner, page fit and metrics.

Defaults: required 3, core responsibility 3, repeated major theme 2, preferred 1, minor keyword 0.5, anything else 1.5.
Override any of them with a JSON object in data/career_compiler/weights.json or the file named by CAREEROS_WEIGHTS.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from app.services.career_compiler.models import Requirement

DEFAULTS = {"required": 3.0, "core_responsibility": 3.0, "repeated_theme": 2.0, "preferred": 1.0, "minor": 0.5,
            "other": 1.5}
CORE_SECTIONS = {"responsibilities", "architecture", "leadership", "ai_ml", "technologies", "domain"}


def _path() -> Path:
    configured = os.environ.get("CAREEROS_WEIGHTS")
    return Path(configured) if configured else Path(__file__).resolve().parents[3] / "data" / "career_compiler" / "weights.json"


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict[str, float]:
    if mtime < 0:
        return dict(DEFAULTS)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {**DEFAULTS, **{k: float(v) for k, v in data.items() if k in DEFAULTS}}


def weights() -> dict[str, float]:
    path = _path()
    return _load(str(path), path.stat().st_mtime if path.is_file() else -1.0)


def requirement_class(req: Requirement) -> str:
    if req.required or req.section == "required_qualifications":
        return "required"
    if req.section == "preferred_qualifications":
        return "preferred"
    if req.section in CORE_SECTIONS and req.importance == "high":
        return "core_responsibility"
    if req.repeated_themes:
        return "repeated_theme"
    if req.importance == "low":
        return "minor"
    return "other"


def requirement_weight(req: Requirement) -> float:
    return weights()[requirement_class(req)]
