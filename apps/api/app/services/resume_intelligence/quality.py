"""Deterministic bullet-quality heuristics.

Never rewrites or invents text - this only nudges selection order so that,
among bullets already matching a requirement, a specific, verified,
already-reviewed professional bullet outranks a vague or unverified one.
"""
from __future__ import annotations

import re

from app.services.story_index import tag_category

ACTION_VERB = re.compile(
    r"^(?:Built|Designed|Implemented|Led|Created|Delivered|Reduced|Improved|Developed|"
    r"Architected|Launched|Migrated|Automated|Optimized|Owned|Drove|Scaled|Redesigned|"
    r"Established|Introduced|Shipped|Cut|Increased|Rebuilt)\b",
    re.I,
)
METRIC = re.compile(r"\d")
VAGUE = re.compile(r"\b(?:responsible for|helped with|worked on|assisted with|involved in|"
                    r"various|multiple|several|things|stuff)\b", re.I)

BASE = 1.0
MIN_SCORE = 0.4
MAX_SCORE = 1.6


def score(candidate: dict, *, tags: frozenset[str] | set[str]) -> float:
    text = (candidate.get("optimizedBullet") or "").strip()
    value = BASE
    if candidate.get("evidenceTier") == "professional":
        value += 0.10
    if candidate.get("approved"):
        value += 0.10
    if METRIC.search(text):
        value += 0.15
    if ACTION_VERB.match(text):
        value += 0.10
    # A named technology is more specific evidence than a behavioural theme.
    technical = sum(1 for tag in tags if tag_category(tag) == "technologies")
    other = len(tags) - technical
    value += min(technical, 4) * 0.06 + min(other, 3) * 0.03
    if VAGUE.search(text):
        value -= 0.25
    if len(text) < 45:
        value -= 0.10
    return max(MIN_SCORE, min(value, MAX_SCORE))
