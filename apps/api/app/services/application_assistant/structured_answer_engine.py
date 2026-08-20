"""Structured Qwen AI Answer Engine with 4-level hierarchy and Zero-Guesswork rules."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services.application_assistant.domain import SensitivityCategory
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

Avoid:
- corporate buzzwords
- exaggerated claims
- generic AI phrasing
- em dashes
- unnecessary adjectives
- repeating the question

When the candidate information does not clearly support an answer, return `supported: false`.

For factual application questions, prefer deterministic profile information over generated text.

For open-ended questions, produce a short human-written response grounded in specific candidate experience.

Return ONLY a JSON object adhering strictly to this schema:
{
  "answer": "...",
  "confidence": 0.94,
  "supported": true,
  "source": ["resume.experience.systems"],
  "reason": "Direct match from candidate experience.",
  "needsUserInput": false
}"""


SENSITIVE_PROMPT_PATTERNS = [
    r"veteran|military|armed forces",
    r"disability|handicap|accommodation",
    r"gender|sex|race|ethnicity|hispanic|latino|sexual orientation|pronoun",
    r"clearance|security clearance|export control|background check",
    r"relocat|willing to move",
    r"salary|compensation|expected pay|rate",
    r"legal attestation|certify|under penalty of perjury|signature|agree to terms",
]


def is_sensitive_question(question_text: str) -> bool:
    norm = question_text.lower()
    return any(re.search(pat, norm) for pat in SENSITIVE_PROMPT_PATTERNS)


def resolve_level_1_deterministic(question_text: str, canonical_key: str, profile: dict[str, Any]) -> str | None:
    norm = question_text.lower()
    key = canonical_key.lower()

    if "first" in key or "first name" in norm or "given name" in norm:
        return profile.get("firstName")
    if "last" in key or "last name" in norm or "family name" in norm:
        return profile.get("lastName")
    if "full" in key or "full name" in norm or norm == "name":
        fn = profile.get("firstName", "")
        ln = profile.get("lastName", "")
        return f"{fn} {ln}".strip() or profile.get("fullName")
    if "email" in key or "email" in norm:
        return profile.get("email")
    if "phone" in key or "phone" in norm or "mobile" in norm:
        return profile.get("phone")
    if "linkedin" in key or "linkedin" in norm:
        return profile.get("linkedin")
    if "github" in key or "github" in norm:
        return profile.get("github")
    if "portfolio" in key or "website" in norm:
        return profile.get("portfolio")
    if "location" in key or "city" in norm or "where are you located" in norm:
        return profile.get("location")
    if "company" in key or "current company" in norm or "employer" in norm:
        return profile.get("currentCompany") or profile.get("currentTitle")
    if "authorization" in key or "authorized to work" in norm:
        return "Yes" if profile.get("workAuthorization") != "No" else "No"
    if "sponsorship" in key or "sponsor" in norm or "require visa" in norm:
        return "No" if profile.get("requiresSponsorship") is False else "Yes"
    if any(k in norm for k in ("resume", "cv", "curriculum vitae", "attach resume", "upload resume")) or "resume" in key:
        return profile.get("resumePath") or profile.get("resumeUrl") or profile.get("resumeFilename") or "resume.pdf"
    if "cover letter" in norm or "cover_letter" in key:
        return profile.get("coverLetterPath") or profile.get("coverLetterUrl") or profile.get("coverLetterFilename") or "cover_letter.pdf"

    return None


def resolve_level_2_answer_library(db: Session | list[dict[str, Any]] | None, question_text: str) -> str | None:
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
                return str(entry.get("value") or "")
    return None


async def resolve_level_3_llm(
    question_text: str,
    options: list[str] | None,
    profile: dict[str, Any],
    resume_text: str = "",
) -> dict[str, Any]:
    prompt = f"""Question: {question_text}
Available Options: {json.dumps(options or [])}

Candidate Profile:
{json.dumps(profile, indent=2)}

Resume Text Snippet:
{resume_text[:2000]}"""

    try:
        raw_response = await call_llm(SYSTEM_ANSWERING_PROMPT, prompt)
        json_match = re.search(r"\{.*\}", raw_response, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
            return parsed
    except Exception as exc:
        pass

    return {
        "answer": "",
        "confidence": 0.0,
        "supported": False,
        "source": [],
        "reason": "LLM failed or unsupported",
        "needsUserInput": True,
    }


async def resolve_application_question(
    db: Session | list[dict[str, Any]] | None = None,
    question_text: str = "",
    canonical_key: str = "",
    options: list[str] | None = None,
    profile: dict[str, Any] | None = None,
    resume_text: str = "",
) -> dict[str, Any]:
    """Resolve an application question using the 4-level hierarchy."""
    prof = profile or {}

    # Sensitive/ambiguous safety check -> Level 4 Stage
    if is_sensitive_question(question_text):
        return {
            "answer": "",
            "confidence": 0.0,
            "supported": False,
            "source": ["safety_policy"],
            "reason": "Sensitive or demographic question requires user review",
            "needsUserInput": True,
            "level": 4,
        }

    # Level 1: Deterministic profile
    l1 = resolve_level_1_deterministic(question_text, canonical_key, prof)
    if l1:
        return {
            "answer": l1,
            "confidence": 1.0,
            "supported": True,
            "source": ["profile.deterministic"],
            "reason": "Matched candidate profile field",
            "needsUserInput": False,
            "level": 1,
        }

    # Level 2: Approved answer library
    l2 = resolve_level_2_answer_library(db, question_text)
    if l2:
        return {
            "answer": l2,
            "confidence": 0.98,
            "supported": True,
            "source": ["answer_library"],
            "reason": "Matched previously approved CareerOS answer",
            "needsUserInput": False,
            "level": 2,
        }

    # Level 3: Grounded Qwen LLM
    l3 = await resolve_level_3_llm(question_text, options, prof, resume_text)
    if l3.get("supported") and l3.get("confidence", 0.0) >= 0.85 and not l3.get("needsUserInput"):
        l3["level"] = 3
        return l3

    # Level 4: Stage for user review
    return {
        "answer": l3.get("answer", ""),
        "confidence": l3.get("confidence", 0.0),
        "supported": False,
        "source": l3.get("source", []),
        "reason": l3.get("reason") or "Insufficient confidence to answer automatically",
        "needsUserInput": True,
        "level": 4,
    }
