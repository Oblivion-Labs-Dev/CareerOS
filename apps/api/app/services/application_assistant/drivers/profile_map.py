"""Deterministic question → answer mapping for ATS forms.

Rules (pinned):
- Contact facts (name, email, phone, location, links, current role/company)
  map straight from the stored candidate profile — deterministic, no LLM.
- An approved answer (from the answer library / previously approved questions)
  always beats a fresh inference.
- Salary expectations, sponsorship, eligibility, cover letters, signatures and
  any required question with no deterministic mapping route to REVIEW —
  ``mappingSource=review_required`` with a reason. They are NEVER guessed.
- CAPTCHA / MFA / assessment elements classify the flow as MANUAL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .base import FormQuestion, QuestionType

# Tokens that classify a question as sensitive/ambiguous — never auto-answered.
_REVIEW_TOKENS = (
    r"salary",
    r"compensation",
    r"expected pay",
    r"sponsor",
    r"visa",
    r"citizenship",
    r"authoriz",
    r"eligible to work",
    r"notice period",
    r"start date",
    r"earliest start",
    r"cover letter",
    r"gender",
    r"ethnicit",
    r"race",
    r"disability",
    r"veteran",
    r"lgbt",
    r"sexual orientation",
    r"signature",
)

# Hard stop: prohibited automation targets.
_MANUAL_TOKENS = (
    r"captcha",
    r"recaptcha",
    r"hcaptcha",
    r"two[- ]factor",
    r"otp",
    r"assessment",
    r"personality test",
    r"video interview",
    r"hirevue",
)

# Field-name/label tokens → profile keys (checked in order; first hit wins).
_PROFILE_PATTERNS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("first name", "given name", "firstname"), "first_name", "profile"),
    (("last name", "surname", "family name", "lastname"), "last_name", "profile"),
    (("full name", "your name"), "full_name", "profile"),
    (("email",), "email", "profile"),
    (("phone", "mobile", "contact number"), "phone", "profile"),
    (("linkedin",), "linkedin_url", "profile"),
    (("github",), "github_url", "profile"),
    (("portfolio", "personal website", "website", "personal site"), "portfolio_url", "profile"),
    (("current company", "employer", "current employer"), "current_company", "profile"),
    (("current title", "job title", "current position", "most recent job"), "current_title", "profile"),
    (("location", "city", "where are you based", "current location"), "location", "profile"),
)


@dataclass
class MappingResult:
    questions: list[FormQuestion] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    manual_reasons: list[str] = field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _pick_profile(profile: dict[str, Any], key: str) -> str:
    """Profile values may live flat or nested under 'contact'/'links'."""

    for container in (profile.get("contact") or {}, profile.get("links") or {}, profile):
        for alias in (key, _camel(key)):
            value = container.get(alias)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, (int, float)):
                return str(value)
    # Deterministic composition: "full name" from stored first/last parts.
    if key == "full_name":
        first = _pick_profile(profile, "first_name")
        last = _pick_profile(profile, "last_name")
        if first and last:
            return f"{first} {last}"
    return ""


def _camel(key: str) -> str:
    parts = key.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def _label_for_field(raw: dict[str, Any]) -> str:
    return str(raw.get("label") or "").strip() or str(raw.get("name") or "").strip()


def _classify_sensitive(norm_label: str, norm_name: str) -> str | None:
    """Return 'manual' or 'review' when the question must not be auto-answered."""

    if any(re.search(t, norm_label) or re.search(t, norm_name) for t in _MANUAL_TOKENS):
        return "manual"
    if any(re.search(t, norm_label) or re.search(t, norm_name) for t in _REVIEW_TOKENS):
        return "review"
    return None


def map_questions(
    raw_fields: list[dict[str, Any]],
    profile: dict[str, Any],
    approved_answers: dict[str, str],
) -> MappingResult:
    result = MappingResult()
    for raw in raw_fields:
        name = str(raw.get("name") or "")
        label = _label_for_field(raw)
        qtype = raw.get("type") or "unknown"
        norm_label = _norm(label)
        norm_name = _norm(name)

        question = FormQuestion(
            key=name or label,
            label=label,
            type=qtype,
            required=bool(raw.get("required")),
            options=list(raw.get("options") or []),
        )

        if qtype == "file":
            question.mapping_source = "profile"
            question.mapped_value = "RESUME"
            question.confidence = 0.9
            question.type = QuestionType.FILE
            result.questions.append(question)
            continue

        # 1. Approved answers dominate (previously human-approved phrasing).
        for bucket, source in ((approved_answers, "approved_answer"),):
            for answer_key, answer_value in bucket.items():
                norm_akey = _norm(answer_key)
                if norm_akey and (norm_akey in norm_label or norm_akey in norm_name):
                    question.mapped_value = answer_value
                    question.mapping_source = source
                    question.confidence = 1.0
                    break
            if question.mapping_source == source:
                break
        if question.mapping_source == "approved_answer":
            result.questions.append(question)
            continue

        # 2. Manual-only controls.
        sensitive = _classify_sensitive(norm_label, norm_name)
        if sensitive == "manual":
            question.mapping_source = "review_required"
            question.mapped_value = None
            result.manual_reasons.append(
                f"Prohibited automation target: {label!r} (CAPTCHA/MFA/assessment)"
            )
            result.questions.append(question)
            continue
        if sensitive == "review":
            question.mapping_source = "review_required"
            question.mapped_value = None
            result.review_reasons.append(
                f"Sensitive/ambiguous question requires human review: {label!r}"
            )
            result.questions.append(question)
            continue

        # 3. Deterministic profile mapping.
        mapped = False
        for patterns, profile_key, source in _PROFILE_PATTERNS:
            if any(p in norm_label or p in norm_name for p in patterns):
                value = _pick_profile(profile, profile_key)
                if value:
                    question.mapped_value = value
                    question.mapping_source = source
                    question.confidence = 0.8
                    mapped = True
                break
        if mapped:
            result.questions.append(question)
            continue

        # 4. Unknown/unmapped: required → REVIEW, optional → left blank.
        question.mapping_source = "review_required"
        question.mapped_value = None
        if question.required:
            result.review_reasons.append(
                f"Required question has no deterministic mapping: {label!r}"
            )
        result.questions.append(question)

    return result
