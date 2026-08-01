"""Answer classification and safety rules for Application Assistant."""

from __future__ import annotations

import re
from typing import Any

from app.services.application_assistant.css_selectors import normalize_css_selector
from app.services.application_assistant.domain import (
    AnswerClassification,
    SensitivityCategory,
)

_PLACEHOLDER_ANSWER_VALUES = frozenset({"-", "—", "", "na", "n/a", "none", "null"})


def _is_placeholder_answer(value: Any) -> bool:
    return str(value or "").strip().lower() in _PLACEHOLDER_ANSWER_VALUES


# Patterns that identify sensitive questions — never infer answers
SENSITIVE_PATTERNS: dict[SensitivityCategory, list[str]] = {
    SensitivityCategory.WORK_AUTHORIZATION: [
        r"work\s+authoriz",
        r"legally\s+authorized",
        r"eligible\s+to\s+work",
        r"right\s+to\s+work",
    ],
    SensitivityCategory.IMMIGRATION: [
        r"visa\s+sponsor",
        r"require\s+sponsor",
        r"immigration",
        r"h-?1b",
    ],
    SensitivityCategory.DISABILITY: [
        r"disabilit",
        r"accommodat",
    ],
    SensitivityCategory.VETERAN: [
        r"veteran",
        r"military\s+service",
        r"armed\s+forces",
    ],
    SensitivityCategory.DEMOGRAPHIC: [
        r"\brace\b",
        r"ethnicit",
        r"\bgender\b",
        r"sexual\s+orient",
        r"\bhispanic\b",
        r"pronouns",
        r"lgbtq",
    ],
    SensitivityCategory.CRIMINAL: [
        r"criminal",
        r"convict",
        r"felon",
        r"background\s+check",
    ],
    SensitivityCategory.CLEARANCE: [
        r"security\s+clearance",
        r"clearance\s+level",
    ],
    SensitivityCategory.SALARY: [
        r"salary\s+expect",
        r"compensation\s+expect",
        r"desired\s+salary",
        r"pay\s+expect",
    ],
    SensitivityCategory.CONSENT: [
        r"consent",
        r"agree\s+to",
        r"acknowledge",
        r"certify",
        r"confirm\s+that",
    ],
    SensitivityCategory.DECLARATION: [
        r"declaration",
        r"accuracy",
        r"truthful",
        r"attest",
    ],
    SensitivityCategory.SIGNATURE: [
        r"signature",
        r"sign\s+below",
        r"electronic\s+sign",
    ],
}

MANUAL_ONLY_PATTERNS = [
    r"signature",
    r"electronic\s+sign",
    r"captcha",
    r"recaptcha",
    r"verify\s+you\s+are\s+human",
    r"i\s+agree",
    r"i\s+certify",
    r"i\s+confirm",
    r"decline\s+to\s+answer",
]

# Profile keys that map to verified answers (order matters — specific keys before generic ones)
PROFILE_FIELD_ORDER = [
    "firstName",
    "lastName",
    "currentCompany",
    "currentTitle",
    "fullName",
    "email",
    "phone",
    "phoneCountry",
    "location",
    "linkedin",
    "github",
    "portfolio",
    "gender",
    "transgender",
    "sexualOrientation",
    "raceEthnicity",
    "hispanic",
    "veteran",
    "disability",
    "pronouns",
    "workAuthorization",
    "sponsorship",
    "salaryExpectations",
]

PROFILE_FIELD_MAP: dict[str, list[str]] = {
    "firstName": [r"first\s*name", r"given\s*name"],
    "lastName": [r"last\s*name", r"family\s*name", r"surname"],
    "currentCompany": [
        r"name\s+of\s+(?:your\s+)?(?:current|previous|recent|last|most\s+recent).{0,40}company",
        r"(?:current|most\s+recent|previous|prior|last).{0,30}company",
        r"company\s+name",
        r"(?:current|present)\s+employer",
        r"employer\s+name",
        r"^employer\b",
    ],
    "currentTitle": [
        r"(?:current|most\s+recent|previous|prior|last).{0,30}(?:job\s+)?title",
        r"current\s+position",
        r"job\s+title",
        r"position\s+title",
    ],
    "fullName": [r"full\s*name", r"legal\s*name", r"^name\s*\*?$", r"^your\s+name\b"],
    "email": [r"e-?mail", r"email\s*address"],
    "phone": [r"phone", r"mobile", r"telephone", r"cell"],
    "phoneCountry": [r"^country\s*\*?$", r"country\s+code", r"dial\s+code"],
    "location": [r"location", r"city", r"address", r"country\s+of\s+residence", r"where do you live"],
    "linkedin": [r"linkedin"],
    "github": [r"github"],
    "portfolio": [r"portfolio", r"personal\s*website", r"website"],
    "workAuthorization": [r"work\s+authoriz", r"legally\s+authorized"],
    "sponsorship": [r"visa\s+sponsor", r"require\s+sponsor"],
    "salaryExpectations": [r"salary", r"compensation\s+expect"],
    "gender": [r"gender\s+identity", r"\bgender\b", r"identify\s+with.*gender"],
    "transgender": [r"transgender"],
    "sexualOrientation": [r"sexual\s+orient"],
    "raceEthnicity": [r"ethnicit", r"\brace\b", r"ethnic\s+background", r"identify\s+with.*ethnic"],
    "hispanic": [r"\bhispanic\b", r"latino"],
    "veteran": [r"veteran", r"military\s+service", r"served\s+in\s+the\s+military"],
    "disability": [r"disabilit", r"\bada\b", r"live\s+with\s+a\s+disability"],
    "pronouns": [r"\bpronouns\b"],
}

# Fields that must never be inferred from unrelated data
NEVER_INFER_FIELDS = {
    "workAuthorization",
    "sponsorship",
    "salaryExpectations",
    "securityClearance",
    "willingToRelocate",
}


def detect_sensitivity(label: str, help_text: str = "") -> SensitivityCategory:
    """Detect sensitivity category from field label and help text."""
    text = f"{label} {help_text}".lower()
    for category, patterns in SENSITIVE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.I):
                return category
    return SensitivityCategory.NONE


def is_manual_only_field(label: str, field_type: str = "") -> bool:
    """Check if a field must be completed manually."""
    text = label.lower()
    if field_type.lower() == "signature":
        return True
    return any(re.search(p, text, re.I) for p in MANUAL_ONLY_PATTERNS)


def normalize_field_key(label: str) -> str:
    """Normalize a field label to a stable key."""
    key = label.lower().strip()
    key = re.sub(r"[^\w\s]", "", key)
    key = re.sub(r"\s+", "_", key)
    return key.strip("_")[:64]


def is_phone_country_search_field(
    label: str,
    *,
    field_id: str = "",
    selector_hint: str = "",
    name: str = "",
) -> bool:
    """Intl-tel-input search box inside the dial-code dropdown — not a user question."""
    label_norm = label.lower().strip()
    selector = (selector_hint or "").lower()
    if "iti" in selector and "search" in selector:
        return True
    if label_norm == "search" and ("iti" in selector or name.startswith("iti")):
        return True
    return False


def is_phone_country_field(
    label: str,
    *,
    field_id: str = "",
    selector_hint: str = "",
    name: str = "",
) -> bool:
    """Greenhouse intl-tel-input dial-code picker shown as Country next to Phone."""
    if is_phone_country_search_field(label, field_id=field_id, selector_hint=selector_hint, name=name):
        return False
    label_norm = re.sub(r"[^\w\s]", "", label.lower()).strip()
    selector = normalize_css_selector(selector_hint or "").lower()
    if field_id == "country" or name == "country":
        return True
    if selector in ("#country", "[name='country']", '[id="country"]'):
        return True
    if label_norm == "country" and (
        "country" in selector or "iti" in selector
    ):
        return True
    return False


def infer_phone_country(profile: dict[str, Any] | None) -> str:
    """Best-effort country name for intl-tel-input from profile phone metadata."""
    if not profile:
        return "United States"
    explicit = profile.get("phoneCountry") or profile.get("phone_country") or profile.get("country")
    if explicit and str(explicit).strip():
        text = str(explicit).strip()
        if "," not in text and len(text.split()) <= 4:
            return text
    phone = str(profile.get("phone") or "").strip()
    if phone.startswith("+1") or re.match(r"^1[\s\-]?\(?\d{3}", phone) or re.match(r"^\(\d{3}\)", phone):
        return "United States"
    location = str(profile.get("location") or "")
    if re.search(r"\b(WA|CA|NY|TX|OR|United States|USA|U\.S\.)\b", location, re.I):
        return "United States"
    return "United States"


def should_skip_autofill_field(field: dict[str, Any]) -> bool:
    """Fields that should never be auto-filled (UI chrome, internal search boxes)."""
    selector = str(field.get("selectorHint") or "").lower()
    if "iti" in selector and "search" in selector:
        return True
    label = str(field.get("label") or "")
    return is_phone_country_search_field(
        label,
        field_id=str(field.get("id") or field.get("fieldId") or ""),
        selector_hint=selector,
        name=str(field.get("name") or ""),
    )


def match_screening_answer(label: str, profile: dict[str, Any] | None) -> tuple[str, Any] | None:
    """Match a field label to a saved screening answer on the profile."""
    if not profile:
        return None
    text = label.lower()
    norm_label = normalize_field_key(label)
    for entry in profile.get("screeningAnswers") or []:
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question") or "")
        if question and normalize_field_key(question) == norm_label:
            answer = entry.get("answer")
            if answer is not None and str(answer).strip():
                return str(entry.get("id") or norm_label), answer
        for pattern in entry.get("matchPatterns") or []:
            try:
                if re.search(str(pattern), text, re.I):
                    answer = entry.get("answer")
                    if answer is not None and str(answer).strip():
                        return str(entry.get("id") or norm_label), answer
            except re.error:
                continue
    return None


def match_profile_key(
    label: str,
    *,
    name: str = "",
    field_id: str = "",
    selector_hint: str = "",
) -> str | None:
    """Match a field label to a profile key."""
    if is_phone_country_search_field(label, field_id=field_id, selector_hint=selector_hint, name=name):
        return None
    if is_phone_country_field(label, name=name, field_id=field_id, selector_hint=selector_hint):
        return "phoneCountry"
    text = label.lower()
    for profile_key in PROFILE_FIELD_ORDER:
        for pattern in PROFILE_FIELD_MAP.get(profile_key, []):
            if re.search(pattern, text, re.I):
                if profile_key == "fullName" and re.search(r"company|employer|organization", text, re.I):
                    continue
                return profile_key
    return None


def get_profile_value(profile: dict[str, Any], profile_key: str) -> Any:
    """Resolve a profile value with sensible fallbacks for employment fields."""
    direct = profile.get(profile_key)
    if direct is not None and str(direct).strip():
        return direct

    aliases = {
        "currentCompany": ("current_company", "employer", "company"),
        "currentTitle": ("current_title", "jobTitle", "title"),
    }.get(profile_key, ())

    for alt in aliases:
        value = profile.get(alt)
        if value is not None and str(value).strip():
            return value

    if profile_key == "currentCompany":
        experience = profile.get("workExperience") or profile.get("experience") or []
        if isinstance(experience, list):
            for job in experience:
                if isinstance(job, dict) and job.get("currentlyEmployed") and job.get("company"):
                    return job.get("company")
            if experience and isinstance(experience[0], dict) and experience[0].get("company"):
                return experience[0].get("company")

    if profile_key == "currentTitle":
        experience = profile.get("workExperience") or profile.get("experience") or []
        if isinstance(experience, list):
            for job in experience:
                if isinstance(job, dict) and job.get("currentlyEmployed") and job.get("jobTitle"):
                    return job.get("jobTitle")
            if experience and isinstance(experience[0], dict) and experience[0].get("jobTitle"):
                return experience[0].get("jobTitle")

    if profile_key == "phoneCountry":
        return infer_phone_country(profile)

    return None


def _value_looks_like_wrong_mapping(profile_key: str, value: Any, profile: dict[str, Any]) -> bool:
    """Block obvious mismatches like putting a person's name in a company field."""
    if not value or not profile:
        return False
    text = str(value).strip().lower()
    if not text:
        return False

    if profile_key == "currentCompany":
        full_name = str(profile.get("fullName") or "").strip().lower()
        first = str(profile.get("firstName") or "").strip().lower()
        last = str(profile.get("lastName") or "").strip().lower()
        if text == full_name or text == f"{first} {last}".strip():
            return True
    if profile_key == "phoneCountry" and ("," in text or re.search(r"\b\d{3}\b", text)):
        return True
    return False


def classify_answer(
    *,
    label: str,
    help_text: str = "",
    field_type: str = "",
    profile: dict[str, Any] | None = None,
    answer_library: list[dict[str, Any]] | None = None,
    allow_inferred: bool = False,
    name: str = "",
    field_id: str = "",
    selector_hint: str = "",
) -> tuple[AnswerClassification, Any, float, str, SensitivityCategory]:
    """
    Classify an answer for a form field.

    Returns: (classification, value, confidence, source, sensitivity)
    """
    sensitivity = detect_sensitivity(label, help_text)

    if should_skip_autofill_field(
        {"label": label, "name": name, "id": field_id, "selectorHint": selector_hint},
    ):
        return AnswerClassification.MANUAL_ONLY, None, 0.0, "ui_chrome", sensitivity

    if is_manual_only_field(label, field_type):
        return AnswerClassification.MANUAL_ONLY, None, 0.0, "safety_rule", sensitivity

    if sensitivity != SensitivityCategory.NONE:
        # Sensitive fields: only use verified profile or answer library data (never guess).
        profile_key = match_profile_key(label, name=name, field_id=field_id, selector_hint=selector_hint)
        if profile_key and profile:
            value = get_profile_value(profile, profile_key)
            if value and str(value).strip() and not _value_looks_like_wrong_mapping(profile_key, value, profile):
                return AnswerClassification.VERIFIED, value, 1.0, f"profile.{profile_key}", sensitivity
        screening = match_screening_answer(label, profile)
        if screening:
            _sid, sval = screening
            if sval is not None and str(sval).strip():
                return AnswerClassification.VERIFIED, sval, 1.0, f"profile.screeningAnswers.{_sid}", sensitivity
        # Check answer library for verified sensitive answers
        if answer_library:
            norm_key = normalize_field_key(label)
            for entry in answer_library:
                if entry.get("verificationStatus") != "verified":
                    continue
                if entry.get("normalizedKey") == norm_key or norm_key in [
                    normalize_field_key(v) for v in entry.get("questionVariants", [])
                ]:
                    if _is_placeholder_answer(entry.get("value")):
                        continue
                    return (
                        AnswerClassification.VERIFIED,
                        entry.get("value"),
                        1.0,
                        f"answer_library.{entry.get('id', '')}",
                        sensitivity,
                    )
        return AnswerClassification.UNKNOWN, None, 0.0, "", sensitivity

    # Non-sensitive: try profile mapping
    profile_key = match_profile_key(label, name=name, field_id=field_id, selector_hint=selector_hint)
    if profile_key and profile:
        value = get_profile_value(profile, profile_key)
        if value and str(value).strip() and not _value_looks_like_wrong_mapping(profile_key, value, profile):
            return AnswerClassification.VERIFIED, value, 1.0, f"profile.{profile_key}", sensitivity

    screening = match_screening_answer(label, profile)
    if screening:
        _sid, sval = screening
        if sval is not None and str(sval).strip():
            return AnswerClassification.VERIFIED, sval, 1.0, f"profile.screeningAnswers.{_sid}", sensitivity

    # Check answer library
    if answer_library:
        norm_key = normalize_field_key(label)
        for entry in answer_library:
            if entry.get("verificationStatus") == "disabled":
                continue
            entry_key = entry.get("normalizedKey", "")
            variants = [normalize_field_key(v) for v in entry.get("questionVariants", [])]
            if entry_key == norm_key or norm_key in variants:
                if _is_placeholder_answer(entry.get("value")):
                    continue
                status = entry.get("verificationStatus", "verified")
                if status == "verified":
                    return (
                        AnswerClassification.VERIFIED,
                        entry.get("value"),
                        1.0,
                        f"answer_library.{entry.get('id', '')}",
                        sensitivity,
                    )
                if status == "draft" and allow_inferred:
                    return (
                        AnswerClassification.INFERRED,
                        entry.get("value"),
                        0.6,
                        f"answer_library.{entry.get('id', '')}",
                        sensitivity,
                    )

    return AnswerClassification.UNKNOWN, None, 0.0, "", sensitivity


def count_classifications(fields: list[dict[str, Any]]) -> dict[str, int]:
    """Count fields by classification."""
    counts = {
        "verified": 0,
        "inferred": 0,
        "unknown": 0,
        "conflict": 0,
        "manual_only": 0,
    }
    for field in fields:
        cls = field.get("classification", "unknown")
        if cls in counts:
            counts[cls] += 1
    return counts
