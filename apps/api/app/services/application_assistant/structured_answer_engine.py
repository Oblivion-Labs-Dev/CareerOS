"""Structured answer engine: deterministic profile rules, then the saved answer library, then review."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services.application_assistant.ats_plugin_reference import (
    classify_canonical_key,
    extract_canonical_value,
    pick_best_matching_option,
)
from app.services.application_assistant.persistence import list_answer_library

logger = logging.getLogger("careeros.answers")



SENSITIVE_PROMPT_PATTERNS = [
    r"clearance|security clearance|export control|polygraph",
    r"legal attestation|under penalty of perjury|sign your full legal name",
]


def is_sensitive_question(question_text: str) -> bool:
    norm = question_text.lower()
    return any(re.search(pat, norm) for pat in SENSITIVE_PROMPT_PATTERNS)


def resolve_level_1_deterministic(
    question_text: str,
    canonical_key: str,
    profile: dict[str, Any],
    options: list[str] | None = None,
) -> tuple[str | None, str]:
    """Level 1: Resolve deterministic answer using plugin canonical rules."""
    key = canonical_key or classify_canonical_key(question_text) or ""
    if not key:
        return None, ""

    val, reason = extract_canonical_value(key, profile, options)
    if val is not None and str(val).strip():
        # If options are present and value is not in options, try option matcher
        if options and str(val) not in options:
            matched_opt = pick_best_matching_option(options, str(val))
            if matched_opt:
                return matched_opt, f"Matched {key} option"
        return str(val).strip(), reason or f"Profile {key}"

    return None, ""


def resolve_level_2_answer_library(
    db: Session | list[dict[str, Any]] | None,
    question_text: str,
) -> tuple[str | None, str]:
    """Level 2: Approved answer library matching."""
    if isinstance(db, list):
        entries = db
    elif db is not None:
        entries = list_answer_library(db)
    else:
        entries = []
    norm = question_text.strip().lower()
    for entry in entries:
        for variant in entry.get("questionVariants", []):
            if variant.strip().lower() == norm:
                return str(entry.get("value") or ""), "Matched saved answer library entry"
    return None, ""


async def resolve_application_question(
    db: Session | list[dict[str, Any]] | None = None,
    question_text: str = "",
    canonical_key: str = "",
    options: list[str] | None = None,
    profile: dict[str, Any] | None = None,
    company: str = "",
    role: str = "",
    resume_text: str = "",
    job_description: str = "",
) -> dict[str, Any]:
    """Resolve an application question: safety policy, profile rules, answer library, else review."""
    prof = profile or {}

    # Sensitive / legal signature questions require user review
    if is_sensitive_question(question_text):
        return {
            "answer": "",
            "confidence": 0.0,
            "supported": False,
            "source": ["safety_policy"],
            "reason": "Legal signature or clearance question requires candidate review",
            "needsUserInput": True,
            "level": 4,
        }

    # Level 1: Deterministic plugin reference rules
    l1_val, l1_reason = resolve_level_1_deterministic(question_text, canonical_key, prof, options)
    if l1_val:
        return {
            "answer": l1_val,
            "confidence": 1.0,
            "supported": True,
            "source": ["profile.deterministic"],
            "reason": l1_reason or "Matched candidate profile field",
            "needsUserInput": False,
            "level": 1,
        }

    # Level 2: Approved answer library
    l2_val, l2_reason = resolve_level_2_answer_library(db, question_text)
    if l2_val:
        return {
            "answer": l2_val,
            "confidence": 0.98,
            "supported": True,
            "source": ["answer_library"],
            "reason": l2_reason or "Matched previously approved CareerOS answer",
            "needsUserInput": False,
            "level": 2,
        }

    # Level 3: nothing deterministic answers this question. Autopilot makes no
    # model calls (owner decision, 2026-11-01), so the honest outcome is to
    # stage it for the candidate rather than invent an answer.
    return {
        "answer": "",
        "confidence": 0.0,
        "supported": False,
        "source": [],
        "reason": "No profile field or saved answer matches this question; staged for candidate input",
        "needsUserInput": True,
        "level": 4,
    }
