"""Server-controlled canonical field keys and deterministic value resolution."""

from __future__ import annotations

import re
from typing import Any

from app.services.application_assistant.answer_classification import (
    AnswerClassification,
    detect_sensitivity,
    get_profile_value,
    is_manual_only_field,
    match_profile_key,
    normalize_field_key,
)
from app.services.application_assistant.domain import SensitivityCategory

# Registry keys the model may return (plus custom.<approved-answer-key>).
CANONICAL_KEYS: frozenset[str] = frozenset(
    {
        "identity.first_name",
        "identity.last_name",
        "identity.full_name",
        "contact.email",
        "contact.phone",
        "location.city",
        "location.state",
        "location.full",
        "links.linkedin",
        "links.github",
        "links.portfolio",
        "employment.current.company",
        "employment.current.title",
        "employment.years_experience",
        "compliance.work_authorization",
        "compliance.sponsorship",
        "compensation.salary_expectation",
        "demographics.gender",
        "demographics.transgender",
        "demographics.sexual_orientation",
        "demographics.race_ethnicity",
        "demographics.hispanic",
        "demographics.veteran",
        "demographics.disability",
        "demographics.pronouns",
        "education.latest.school",
        "documents.selected_resume",
        "documents.cover_letter",
        "unknown",
        "manual_only",
        "sensitive",
        "prohibited",
    }
)

SPECIAL_CANONICAL_KEYS = frozenset({"unknown", "manual_only", "sensitive", "prohibited"})

CUSTOM_PREFIX = "custom."

# Canonical key → legacy profile field used by get_profile_value().
CANONICAL_TO_PROFILE: dict[str, str] = {
    "identity.first_name": "firstName",
    "identity.last_name": "lastName",
    "identity.full_name": "fullName",
    "contact.email": "email",
    "contact.phone": "phone",
    "location.city": "location",
    "location.state": "location",
    "location.full": "location",
    "links.linkedin": "linkedin",
    "links.github": "github",
    "links.portfolio": "portfolio",
    "employment.current.company": "currentCompany",
    "employment.current.title": "currentTitle",
    "employment.years_experience": "yearsExperience",
    "compliance.work_authorization": "workAuthorization",
    "compliance.sponsorship": "sponsorship",
    "compensation.salary_expectation": "salaryExpectations",
    "demographics.gender": "gender",
    "demographics.transgender": "transgender",
    "demographics.sexual_orientation": "sexualOrientation",
    "demographics.race_ethnicity": "raceEthnicity",
    "demographics.hispanic": "hispanic",
    "demographics.veteran": "veteran",
    "demographics.disability": "disability",
    "demographics.pronouns": "pronouns",
}

SENSITIVE_CANONICAL_KEYS = frozenset(
    {
        "compliance.work_authorization",
        "compliance.sponsorship",
        "compensation.salary_expectation",
        "demographics.gender",
        "demographics.transgender",
        "demographics.sexual_orientation",
        "demographics.race_ethnicity",
        "demographics.hispanic",
        "demographics.veteran",
        "demographics.disability",
    }
)

DOCUMENT_CANONICAL_KEYS = frozenset(
    {
        "documents.selected_resume",
        "documents.cover_letter",
    }
)

DOCUMENT_KEY_MAP = {
    "documents.selected_resume": "defaultResume",
    "documents.cover_letter": "defaultCoverLetter",
}

# First canonical wins when multiple keys share one profile field (e.g. location.*).
PROFILE_TO_CANONICAL: dict[str, str] = {}
for _canonical, _profile_key in CANONICAL_TO_PROFILE.items():
    PROFILE_TO_CANONICAL.setdefault(_profile_key, _canonical)


def is_valid_canonical_key(key: str, *, approved_custom_keys: set[str] | None = None) -> bool:
    if key in CANONICAL_KEYS:
        return True
    if key.startswith(CUSTOM_PREFIX):
        suffix = key[len(CUSTOM_PREFIX) :]
        return bool(suffix) and (approved_custom_keys is None or suffix in approved_custom_keys)
    return False


def canonical_to_value_ref(canonical_key: str) -> str:
    if canonical_key.startswith(CUSTOM_PREFIX):
        return f"answer_library.{canonical_key[len(CUSTOM_PREFIX):]}"
    if canonical_key in DOCUMENT_CANONICAL_KEYS:
        return f"documents.{DOCUMENT_KEY_MAP[canonical_key]}"
    profile_key = CANONICAL_TO_PROFILE.get(canonical_key)
    if profile_key:
        return f"profile.{canonical_key}"
    return ""


def resolve_value_ref(
    value_ref: str,
    *,
    profile: dict[str, Any],
    answer_library: list[dict[str, Any]],
    documents: dict[str, Any] | None = None,
    allow_inferred: bool = False,
) -> tuple[str, Any, str] | None:
    """Resolve a valueRef to (classification, value, source). Returns None if unavailable."""
    if value_ref.startswith("profile."):
        canonical = value_ref.removeprefix("profile.")
        profile_key = CANONICAL_TO_PROFILE.get(canonical)
        if not profile_key:
            return None
        value = get_profile_value(profile, profile_key)
        if value is None or not str(value).strip():
            return None
        return AnswerClassification.VERIFIED.value, value, value_ref

    if value_ref.startswith("answer_library."):
        norm = normalize_field_key(value_ref.removeprefix("answer_library."))
        for entry in answer_library:
            entry_key = entry.get("normalizedKey", "")
            variants = [normalize_field_key(v) for v in entry.get("questionVariants", [])]
            if entry_key != norm and norm not in variants:
                continue
            value = entry.get("value")
            if value is None or not str(value).strip():
                return None
            status = entry.get("verificationStatus", "verified")
            if status == "verified":
                return AnswerClassification.VERIFIED.value, value, value_ref
            if status == "draft" and allow_inferred:
                return AnswerClassification.INFERRED.value, value, value_ref
        return None

    if value_ref.startswith("documents."):
        doc_key = value_ref.removeprefix("documents.")
        if documents and documents.get(doc_key):
            return AnswerClassification.VERIFIED.value, doc_key, value_ref
        return None

    return None


def approved_custom_keys(answer_library: list[dict[str, Any]]) -> set[str]:
    return {str(e.get("normalizedKey")) for e in answer_library if e.get("normalizedKey")}


def classify_canonical_for_field(canonical_key: str, label: str, help_text: str = "") -> str:
    if canonical_key in ("manual_only", "prohibited"):
        return AnswerClassification.MANUAL_ONLY.value
    if canonical_key in ("unknown", "sensitive"):
        return AnswerClassification.UNKNOWN.value
    if is_manual_only_field(label):
        return AnswerClassification.MANUAL_ONLY.value
    if detect_sensitivity(label, help_text) != SensitivityCategory.NONE:
        if canonical_key in SENSITIVE_CANONICAL_KEYS:
            return AnswerClassification.VERIFIED.value
        return AnswerClassification.UNKNOWN.value
    return AnswerClassification.VERIFIED.value


def registry_for_prompt(answer_library: list[dict[str, Any]]) -> list[str]:
    keys = sorted(CANONICAL_KEYS - SPECIAL_CANONICAL_KEYS)
    for entry in answer_library:
        norm = entry.get("normalizedKey")
        if norm:
            keys.append(f"{CUSTOM_PREFIX}{norm}")
    keys.extend(sorted(SPECIAL_CANONICAL_KEYS))
    return keys


def registry_context_for_prompt(answer_library: list[dict[str, Any]]) -> dict[str, Any]:
    """Rich registry for AI mapping — includes human-readable saved question wording."""
    saved_answers = []
    for entry in answer_library:
        norm = str(entry.get("normalizedKey") or "")
        if not norm:
            continue
        variants = [str(v) for v in entry.get("questionVariants") or [] if str(v).strip()]
        saved_answers.append(
            {
                "normalizedKey": norm,
                "canonicalKey": f"{CUSTOM_PREFIX}{norm}",
                "questions": variants[:10],
                "hasValue": bool(str(entry.get("value") or "").strip()),
                "sensitivityCategory": entry.get("sensitivityCategory", "none"),
            }
        )
    profile_fields = [
        {"profileKey": profile_key, "canonicalKey": canonical}
        for profile_key, canonical in PROFILE_TO_CANONICAL.items()
    ]
    return {
        "canonicalKeys": sorted(CANONICAL_KEYS - SPECIAL_CANONICAL_KEYS),
        "profileFields": profile_fields,
        "savedAnswers": saved_answers,
    }


def mapping_confidence_tier(confidence: float, *, auto: float, review: float) -> str:
    if confidence >= auto:
        return "auto"
    if confidence >= review:
        return "review"
    return "unknown"


def infer_canonical_from_field(field: dict[str, Any]) -> str | None:
    """Deterministic label → canonical key when the mapping agent fails."""
    label = str(field.get("label") or "")
    help_text = str(field.get("helpText") or field.get("help_text") or "")
    field_type = str(field.get("fieldType") or field.get("field_type") or "").lower()
    combined = f"{label} {help_text}".lower()

    if field_type == "file":
        if re.search(r"resume|curriculum|\bcv\b", combined, re.I):
            return "documents.selected_resume"
        if re.search(r"cover\s*letter", combined, re.I):
            return "documents.cover_letter"

    if re.search(r"\bcountry\b", combined, re.I) and field_type.startswith("select"):
        return "location.city"

    profile_key = match_profile_key(label)
    if profile_key:
        canonical = PROFILE_TO_CANONICAL.get(profile_key)
        if canonical:
            return canonical

    demographic_patterns: list[tuple[str, list[str]]] = [
        ("demographics.gender", [r"gender\s+identity", r"\bgender\b"]),
        ("demographics.transgender", [r"transgender"]),
        ("demographics.sexual_orientation", [r"sexual\s+orient"]),
        ("demographics.race_ethnicity", [r"ethnicit", r"\brace\b"]),
        ("demographics.veteran", [r"veteran", r"military"]),
        ("demographics.disability", [r"disabilit", r"\bada\b"]),
    ]
    combined = f"{label} {help_text}".lower()
    for canonical, patterns in demographic_patterns:
        if any(re.search(p, combined, re.I) for p in patterns):
            return canonical

    return None
