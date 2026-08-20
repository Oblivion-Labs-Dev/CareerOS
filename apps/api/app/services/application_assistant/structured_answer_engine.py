"""Structured Qwen AI Answer Engine with 4-level hierarchy, plugin reference rules, and Zero-Guesswork grounding."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services.application_assistant.ats_plugin_reference import (
    classify_canonical_key,
    extract_canonical_value,
    pick_best_matching_option,
)
from app.services.application_assistant.llm_client import call_llm
from app.services.application_assistant.persistence import list_answer_library


SYSTEM_ANSWERING_PROMPT = """You are the application-answering component inside CareerOS.

Answer the application question using ONLY the candidate information provided.

Never invent:
- experience
- skills
- employment dates
- accomplishments
- education
- certifications
- legal status
- demographic information
- salary history
- personal preferences

Write naturally and concisely.

Writing style:
- Write like a real software engineer filling out a job application.
- Use simple, natural professional English.
- First person ("I built...", "I worked on...", "My experience includes...").
- Keep answers to 2 to 4 concise sentences (40 to 90 words).
- Avoid corporate buzzwords, excessive adjectives, and AI phrasing ("passionate", "spearheaded", "seamlessly", "cutting-edge", "extensive experience").
- Never use em dashes.

When the candidate information does not clearly support an answer, return `supported: false`.

For factual application questions, prefer deterministic profile information over generated text.

If available options are provided, select the option that best matches the candidate's background.

Return ONLY a JSON object adhering strictly to this schema:
{
  "answer": "...",
  "confidence": 0.95,
  "supported": true,
  "source": ["resume.experience"],
  "reason": "Grounded candidate experience match.",
  "needsUserInput": false
}"""


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


async def resolve_level_3_llm(
    question_text: str,
    options: list[str] | None,
    profile: dict[str, Any],
    company: str = "",
    role: str = "",
    resume_text: str = "",
) -> dict[str, Any]:
    """Level 3: Grounded Agent Answer Generator for open-ended or custom screening questions."""
    prompt = f"""Target Company: {company or 'Target Employer'}
Target Role: {role or 'Software Engineer / Target Role'}

Question: {question_text}
Available Options: {json.dumps(options or [])}

Candidate Profile:
{json.dumps(profile, indent=2)}

Candidate Resume Summary:
{resume_text[:2500]}"""

    try:
        raw_response = await call_llm(SYSTEM_ANSWERING_PROMPT, prompt)
        json_match = re.search(r"\{.*\}", raw_response, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
            ans = str(parsed.get("answer") or "").strip()
            # If options were provided and the model returned an option, verify option match
            if options and ans and ans not in options:
                best_opt = pick_best_matching_option(options, ans)
                if best_opt:
                    parsed["answer"] = best_opt
            return parsed
    except Exception:
        pass

    return {
        "answer": "",
        "confidence": 0.0,
        "supported": False,
        "source": [],
        "reason": "Agent answer generation could not ground answer with high confidence",
        "needsUserInput": True,
    }


async def resolve_application_question(
    db: Session | list[dict[str, Any]] | None = None,
    question_text: str = "",
    canonical_key: str = "",
    options: list[str] | None = None,
    profile: dict[str, Any] | None = None,
    company: str = "",
    role: str = "",
    resume_text: str = "",
) -> dict[str, Any]:
    """Resolve an application question using the 4-level hierarchy with plugin reference and agent answer generation."""
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

    # Level 3: Grounded Agent Answer Generator
    l3 = await resolve_level_3_llm(
        question_text=question_text,
        options=options,
        profile=prof,
        company=company,
        role=role,
        resume_text=resume_text,
    )
    if l3.get("supported") and l3.get("confidence", 0.0) >= 0.75 and not l3.get("needsUserInput") and l3.get("answer"):
        l3["level"] = 3
        return l3

    # Level 4: Stage for user review
    return {
        "answer": l3.get("answer", ""),
        "confidence": l3.get("confidence", 0.0),
        "supported": False,
        "source": l3.get("source", []),
        "reason": l3.get("reason") or "Question requires candidate review in Review Center",
        "needsUserInput": True,
        "level": 4,
    }
