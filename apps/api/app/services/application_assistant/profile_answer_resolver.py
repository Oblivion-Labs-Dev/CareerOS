"""Profile-Grounded Answer Resolver — the single authoritative answer source.

Replaces all inline if/elif heuristics in the executor and adapters with
a centralized, profile-driven, auditable resolver.

Resolution order:
  1. Question classification → QuestionType
  2. Canonical profile / deterministic rule → direct lookup
  3. Exact ATS option mapping → match profile value to available options
  4. Validation → cross-check against profile
  5. LLM only if genuinely needed (free-text only, never for sensitive factual)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.db.store import now_iso
from app.services.application_assistant.ats_plugin_reference import (
    pick_best_matching_option,
    APPLICATION_FIELD_DEFAULTS,
)
from app.services.application_assistant.question_classifier import (
    QuestionType,
    classify_question,
    is_sensitive_factual,
)


# ── Resolution method constants ──────────────────────────────────────────────
PROFILE_EXACT = "PROFILE_EXACT"
PROFILE_OPTION_MAPPING = "PROFILE_OPTION_MAPPING"
DETERMINISTIC_RULE = "DETERMINISTIC_RULE"
RESUME_FACT = "RESUME_FACT"
LLM_GENERATED_TEXT = "LLM_GENERATED_TEXT"
USER_OVERRIDE = "USER_OVERRIDE"
UNKNOWN_METHOD = "UNKNOWN"


@dataclass
class AnswerResolution:
    """Complete provenance record for a single resolved answer."""
    field_id: str = ""
    question: str = ""
    question_type: str = ""
    answer: str | None = None
    answer_value: str | None = None   # raw option value if different from display text
    resolution_method: str = UNKNOWN_METHOD
    profile_key: str | None = None
    source_value: Any = None
    confidence: float = 0.0
    validator_status: str = "UNVALIDATED"  # PASS | FAIL | WARN | UNVALIDATED
    resolved_at: str = ""
    model_used: str | None = None
    raw_llm_response: str | None = None
    blocking_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fieldId": self.field_id,
            "question": self.question,
            "questionType": self.question_type,
            "answer": self.answer,
            "answerValue": self.answer_value,
            "resolutionMethod": self.resolution_method,
            "profileKey": self.profile_key,
            "sourceValue": self.source_value,
            "confidence": self.confidence,
            "validatorStatus": self.validator_status,
            "resolvedAt": self.resolved_at,
            "modelUsed": self.model_used,
            "rawLlmResponse": self.raw_llm_response,
            "blockingErrors": self.blocking_errors,
        }


# ── Helper: get structured work auth ─────────────────────────────────────────

def _get_work_auth(profile: dict[str, Any]) -> dict[str, Any]:
    """Extract the structured workAuth object with safe defaults."""
    wa = profile.get("workAuth") or {}
    return {
        "authorizedToWorkInUS": wa.get("authorizedToWorkInUS", True),
        "authorizationType": wa.get("authorizationType", ""),
        "requiresSponsorshipNowOrFuture": wa.get("requiresSponsorshipNowOrFuture",
            str(profile.get("sponsorship", "")).lower() in ("yes", "true", "1")),
        "permanentWorkAuthorization": wa.get("permanentWorkAuthorization", False),
        "usCitizen": wa.get("usCitizen", False),
        "usNational": wa.get("usNational", False),
        "greenCardHolder": wa.get("greenCardHolder", False),
    }


def _get_security(profile: dict[str, Any]) -> dict[str, Any]:
    """Extract the structured security object with safe defaults."""
    sec = profile.get("security") or {}
    return {
        "hasHeldUSSecurityClearance": sec.get("hasHeldUSSecurityClearance", False),
        "eligibleForUSSecurityClearance": sec.get("eligibleForUSSecurityClearance", False),
    }


# ── Option matching with safety ──────────────────────────────────────────────

_RACE_KEYWORDS = frozenset({
    "american indian", "alaska native", "alaskan native",
    "asian", "south asian", "east asian",
    "black", "african american",
    "native hawaiian", "pacific islander",
    "white", "caucasian",
    "two or more", "multiracial",
})

_ETHNICITY_KEYWORDS = frozenset({
    "hispanic", "latino", "latina", "latinx",
    "not hispanic", "non hispanic",
})


def _is_race_option(opt: str) -> bool:
    """Check if an option text is a race choice (not ethnicity)."""
    lower = opt.lower()
    return any(kw in lower for kw in _RACE_KEYWORDS)


def _is_ethnicity_option(opt: str) -> bool:
    """Check if an option text is an ethnicity choice (not race)."""
    lower = opt.lower()
    return any(kw in lower for kw in _ETHNICITY_KEYWORDS)


def _match_option(options: list[str], target: str) -> str | None:
    """Match target to options, returning the best match or None."""
    if not options or not target:
        return None
    return pick_best_matching_option(options, target)


def _find_decline_option(options: list[str]) -> str | None:
    """Find a 'decline to answer' / 'prefer not to say' option."""
    for opt in options:
        lower = opt.lower()
        if any(phrase in lower for phrase in [
            "prefer not", "decline", "do not wish", "don't wish",
            "choose not", "not to answer", "not to say",
        ]):
            return opt
    return None


# ── Core resolver ────────────────────────────────────────────────────────────

def resolve_answer(
    question_text: str,
    profile: dict[str, Any],
    options: list[str] | None = None,
    field_id: str = "",
    question_type: QuestionType | None = None,
) -> AnswerResolution:
    """Resolve an application field answer using the canonical profile.

    This is the single entry point that replaces ALL inline if/elif
    heuristics across the codebase.
    """
    qtype = question_type or classify_question(question_text, field_id, options)
    opts = options or []

    resolution = AnswerResolution(
        field_id=field_id,
        question=question_text,
        question_type=qtype.value,
        resolved_at=now_iso(),
    )

    # Dispatch to type-specific resolver
    resolver = _RESOLVERS.get(qtype)
    if resolver:
        resolver(resolution, profile, opts)
    else:
        _resolve_unknown(resolution, profile, opts)

    return resolution


# ── Type-specific resolvers ──────────────────────────────────────────────────

def _resolve_from_profile(res: AnswerResolution, profile: dict, opts: list[str],
                          profile_key: str, *, fallback: str | None = None) -> None:
    """Generic helper: resolve from a direct profile key."""
    value = profile.get(profile_key)
    if value is not None and str(value).strip():
        answer = str(value).strip()
        if opts:
            matched = _match_option(opts, answer)
            if matched:
                res.answer = matched
                res.resolution_method = PROFILE_OPTION_MAPPING
            else:
                res.answer = answer
                res.resolution_method = PROFILE_EXACT
        else:
            res.answer = answer
            res.resolution_method = PROFILE_EXACT
        res.profile_key = profile_key
        res.source_value = value
        res.confidence = 1.0
        return
    if fallback is not None:
        if opts:
            matched = _match_option(opts, fallback)
            res.answer = matched or fallback
        else:
            res.answer = fallback
        res.resolution_method = DETERMINISTIC_RULE
        res.confidence = 0.95
        res.profile_key = profile_key


def _resolve_first_name(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "firstName")

def _resolve_last_name(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "lastName")

def _resolve_full_name(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    fn = profile.get("firstName", "")
    ln = profile.get("lastName", "")
    full = f"{fn} {ln}".strip() or profile.get("fullName", "")
    if full:
        res.answer = full
        res.resolution_method = PROFILE_EXACT
        res.profile_key = "fullName"
        res.source_value = full
        res.confidence = 1.0

def _resolve_email(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "email")

def _resolve_phone(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "phone")

def _resolve_phone_country(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "phoneCountryCode", fallback="United States")

def _resolve_location(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    loc = profile.get("location") or ""
    city = profile.get("city") or ""
    state = profile.get("state") or ""
    if loc:
        res.answer = loc
    elif city and state:
        res.answer = f"{city}, {state}"
    elif city:
        res.answer = city
    if res.answer:
        res.resolution_method = PROFILE_EXACT
        res.profile_key = "location"
        res.source_value = res.answer
        res.confidence = 1.0

def _resolve_city(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "city")

def _resolve_state(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "state", fallback="Washington")

def _resolve_country(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "country", fallback="United States")

def _resolve_zip(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "zip")

def _resolve_address(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "address")

def _resolve_current_company(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "currentCompany")

def _resolve_current_title(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "currentTitle")

def _resolve_linkedin(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "linkedin")

def _resolve_github(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "github")

def _resolve_website(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    val = profile.get("portfolio") or profile.get("website")
    if val:
        res.answer = str(val)
        res.resolution_method = PROFILE_EXACT
        res.profile_key = "portfolio"
        res.source_value = val
        res.confidence = 1.0

def _resolve_years_experience(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "yearsExperience", fallback="5")


# ── Work Authorization resolvers (the critical fixes) ────────────────────────

def _resolve_work_authorized(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Q: Are you authorized to work in the US? → Yes (for H1B holders)."""
    wa = _get_work_auth(profile)
    answer = "Yes" if wa["authorizedToWorkInUS"] else "No"
    if opts:
        matched = _match_option(opts, answer)
        res.answer = matched or answer
        res.resolution_method = PROFILE_OPTION_MAPPING if matched else PROFILE_EXACT
    else:
        res.answer = answer
        res.resolution_method = PROFILE_EXACT
    res.profile_key = "workAuth.authorizedToWorkInUS"
    res.source_value = wa["authorizedToWorkInUS"]
    res.confidence = 1.0


def _resolve_sponsorship_required(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Q: Will you require sponsorship? → Yes (for H1B).

    BUG FIX: This was previously returning "No" because the heuristic
    confused work authorization with sponsorship. They are separate facts:
    authorized=Yes AND requires_sponsorship=Yes can both be true.
    """
    wa = _get_work_auth(profile)
    answer = "Yes" if wa["requiresSponsorshipNowOrFuture"] else "No"
    if opts:
        matched = _match_option(opts, answer)
        res.answer = matched or answer
        res.resolution_method = PROFILE_OPTION_MAPPING if matched else PROFILE_EXACT
    else:
        res.answer = answer
        res.resolution_method = PROFILE_EXACT
    res.profile_key = "workAuth.requiresSponsorshipNowOrFuture"
    res.source_value = wa["requiresSponsorshipNowOrFuture"]
    res.confidence = 1.0


def _resolve_permanent_work_auth(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Q: Do you have permanent authorization to work in the US? → No (for H1B).

    BUG FIX: This was answering "Yes" because it was confused with
    "authorized to work" (which IS true). Permanent != current.
    """
    wa = _get_work_auth(profile)
    answer = "Yes" if wa["permanentWorkAuthorization"] else "No"
    if opts:
        matched = _match_option(opts, answer)
        res.answer = matched or answer
        res.resolution_method = PROFILE_OPTION_MAPPING if matched else PROFILE_EXACT
    else:
        res.answer = answer
        res.resolution_method = PROFILE_EXACT
    res.profile_key = "workAuth.permanentWorkAuthorization"
    res.source_value = wa["permanentWorkAuthorization"]
    res.confidence = 1.0


def _resolve_citizenship(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Never claim US citizenship unless profile confirms it."""
    wa = _get_work_auth(profile)
    if wa["usCitizen"]:
        answer = "Yes"
    elif wa["usNational"]:
        answer = "Yes"
    else:
        answer = "No"
    if opts:
        matched = _match_option(opts, answer)
        res.answer = matched or answer
        res.resolution_method = PROFILE_OPTION_MAPPING if matched else PROFILE_EXACT
    else:
        res.answer = answer
        res.resolution_method = PROFILE_EXACT
    res.profile_key = "workAuth.usCitizen"
    res.source_value = wa["usCitizen"]
    res.confidence = 1.0


def _resolve_export_control(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Q: Export control / ITAR / EAR / US person → None of the above (for H1B).

    BUG FIX: Previous system selected "A United States citizen or national"
    via fuzzy match. Must never select citizenship options when usCitizen=false.
    """
    wa = _get_work_auth(profile)

    # Only select citizenship/national options if actually true
    if wa["usCitizen"] or wa["usNational"]:
        target = "A United States citizen or national"
    elif wa["greenCardHolder"]:
        target = "A lawful permanent resident"
    else:
        target = "None of the above"

    if opts:
        # SAFETY: Never pick a citizenship option when not a citizen
        if not wa["usCitizen"] and not wa["usNational"]:
            safe_opts = [o for o in opts if not re.search(
                r"united states citizen|u\.s\.\s*citizen|citizen or national",
                o.lower()
            )]
            matched = _match_option(safe_opts, target) if safe_opts else None
            if not matched:
                # Try "None of the above" explicitly
                matched = _match_option(opts, "None of the above") or \
                          _match_option(opts, "None") or \
                          _match_option(opts, "No")
            res.answer = matched or target
        else:
            matched = _match_option(opts, target)
            res.answer = matched or target
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = target
        res.resolution_method = PROFILE_EXACT

    res.profile_key = "workAuth.usCitizen"
    res.source_value = wa["usCitizen"]
    res.confidence = 1.0


# ── Security Clearance resolvers ─────────────────────────────────────────────

def _resolve_clearance_eligibility(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Q: Are you eligible for security clearance? → No.

    BUG FIX: Resume keywords like "security" were being used to infer
    clearance eligibility. Must use only the profile fact.
    """
    sec = _get_security(profile)
    answer = "Yes" if sec["eligibleForUSSecurityClearance"] else "No"
    if opts:
        matched = _match_option(opts, answer) or _match_option(opts, "Not eligible")
        res.answer = matched or answer
        res.resolution_method = PROFILE_OPTION_MAPPING if matched else PROFILE_EXACT
    else:
        res.answer = answer
        res.resolution_method = PROFILE_EXACT
    res.profile_key = "security.eligibleForUSSecurityClearance"
    res.source_value = sec["eligibleForUSSecurityClearance"]
    res.confidence = 1.0


def _resolve_clearance_level(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    sec = _get_security(profile)
    if sec["hasHeldUSSecurityClearance"]:
        answer = profile.get("clearanceLevel", "Secret")
    else:
        answer = "None"
    if opts:
        matched = _match_option(opts, answer) or _match_option(opts, "N/A") or \
                  _match_option(opts, "No clearance held") or _match_option(opts, "None")
        res.answer = matched or answer
        res.resolution_method = PROFILE_OPTION_MAPPING if matched else PROFILE_EXACT
    else:
        res.answer = answer
        res.resolution_method = PROFILE_EXACT
    res.profile_key = "security.hasHeldUSSecurityClearance"
    res.source_value = sec["hasHeldUSSecurityClearance"]
    res.confidence = 1.0


# ── Demographic resolvers (CRITICAL: never cross-contaminate) ────────────────

def _resolve_gender(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """BUG FIX: Was defaulting to 'Decline' instead of using profile.gender='Male'."""
    val = profile.get("gender") or APPLICATION_FIELD_DEFAULTS.get("gender", "Prefer not to answer")
    if opts:
        matched = _match_option(opts, val)
        if matched:
            res.answer = matched
            res.resolution_method = PROFILE_OPTION_MAPPING
        else:
            decline = _find_decline_option(opts)
            res.answer = decline or val
            res.resolution_method = PROFILE_OPTION_MAPPING if decline else PROFILE_EXACT
    else:
        res.answer = val
        res.resolution_method = PROFILE_EXACT
    res.profile_key = "gender"
    res.source_value = val
    res.confidence = 1.0 if profile.get("gender") else 0.8


def _resolve_ethnicity_hispanic(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Q: Are you Hispanic/Latino? → No.

    BUG FIX: Previous system answered "American Indian or Alaskan Native"
    because race options were used for an ethnicity question.
    CRITICAL: Filter out any race options from candidates for this question.
    """
    val = profile.get("hispanic", "No")
    answer = str(val).strip()

    if opts:
        # SAFETY: Remove any race options — they can NEVER be answers to an ethnicity question
        safe_opts = [o for o in opts if not _is_race_option(o)]
        if not safe_opts:
            safe_opts = opts  # fallback to all if filtering removed everything

        matched = _match_option(safe_opts, answer)
        if matched:
            res.answer = matched
        else:
            # Try explicit "No" variants
            no_match = _match_option(safe_opts, "No") or \
                       _match_option(safe_opts, "Not Hispanic") or \
                       _match_option(safe_opts, "Not Hispanic or Latino")
            res.answer = no_match or answer
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = answer
        res.resolution_method = PROFILE_EXACT

    res.profile_key = "hispanic"
    res.source_value = val
    res.confidence = 1.0


def _resolve_race(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Q: What is your race? → Asian.

    SAFETY: Filter out ethnicity options — they can NEVER be answers to a race question.
    """
    val = profile.get("raceEthnicity") or APPLICATION_FIELD_DEFAULTS.get("raceEthnicity", "Prefer not to answer")

    if opts:
        # SAFETY: Remove ethnicity options from race question
        safe_opts = [o for o in opts if not _is_ethnicity_option(o)]
        if not safe_opts:
            safe_opts = opts

        matched = _match_option(safe_opts, val)
        if matched:
            res.answer = matched
        else:
            decline = _find_decline_option(safe_opts)
            res.answer = decline or val
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = val
        res.resolution_method = PROFILE_EXACT

    res.profile_key = "raceEthnicity"
    res.source_value = val
    res.confidence = 1.0 if profile.get("raceEthnicity") else 0.8


def _resolve_transgender(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    val = profile.get("transgender")
    if val:
        answer = str(val)
    else:
        answer = "Decline"
    if opts:
        matched = _match_option(opts, answer) or _find_decline_option(opts) or _match_option(opts, "No")
        res.answer = matched or answer
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = answer
        res.resolution_method = PROFILE_EXACT if val else DETERMINISTIC_RULE
    res.profile_key = "transgender"
    res.source_value = val
    res.confidence = 1.0 if val else 0.8


def _resolve_sexual_orientation(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    val = profile.get("sexualOrientation")
    if val:
        answer = str(val)
    else:
        answer = "Decline"
    if opts:
        matched = _match_option(opts, answer) or _find_decline_option(opts)
        res.answer = matched or answer
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = answer
        res.resolution_method = PROFILE_EXACT if val else DETERMINISTIC_RULE
    res.profile_key = "sexualOrientation"
    res.source_value = val
    res.confidence = 1.0 if val else 0.8


def _resolve_pronouns(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "pronouns", fallback="Prefer not to say")

def _resolve_veteran(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "veteran",
                          fallback=APPLICATION_FIELD_DEFAULTS.get("veteran", "I am not a protected veteran"))

def _resolve_disability(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "disability",
                          fallback=APPLICATION_FIELD_DEFAULTS.get("disability", "No, I don't have a disability"))


# ── Misc resolvers ───────────────────────────────────────────────────────────

def _resolve_how_heard(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """BUG FIX: Was selecting random options. Now uses profile.jobDiscoveryDefault."""
    default = profile.get("jobDiscoveryDefault", "LinkedIn")
    if opts:
        matched = _match_option(opts, default)
        if not matched:
            matched = _match_option(opts, "Other") or _match_option(opts, "Job Board")
        res.answer = matched or default
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = default
        res.resolution_method = PROFILE_EXACT
    res.profile_key = "jobDiscoveryDefault"
    res.source_value = default
    res.confidence = 0.9


def _resolve_relocate(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "relocate", fallback="Yes")

def _resolve_salary(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "salaryExpectations", fallback="Open / Negotiable")

def _resolve_notice_period(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "noticePeriod", fallback="2 weeks")

def _resolve_sms_consent(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "smsConsent",
                          fallback=APPLICATION_FIELD_DEFAULTS.get("smsConsent", "No"))

def _resolve_english_proficiency(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    target = "Fluent"
    if opts:
        matched = _match_option(opts, target) or _match_option(opts, "Professional") or _match_option(opts, "Native")
        res.answer = matched or target
    else:
        res.answer = target
    res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.95

def _resolve_privacy_consent(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    if opts:
        res.answer = _match_option(opts, "Yes") or _match_option(opts, "I acknowledge") or "Yes"
    else:
        res.answer = "Yes"
    res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.95

def _resolve_accuracy_confirmation(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    if opts:
        res.answer = _match_option(opts, "Yes") or "Yes"
    else:
        res.answer = "Yes"
    res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.95

def _resolve_background_check(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    if opts:
        res.answer = _match_option(opts, "Yes") or "Yes"
    else:
        res.answer = "Yes"
    res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.95

def _resolve_company_history(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    if opts:
        res.answer = _match_option(opts, "No") or "No"
    else:
        res.answer = "No"
    res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.95

def _resolve_school(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "school")

def _resolve_degree(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "degree", fallback="Bachelor's Degree")

def _resolve_gpa(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "gpa", fallback="3.5")

def _resolve_transcript(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    if opts:
        res.answer = _match_option(opts, "Yes") or "Yes"
    else:
        res.answer = "Yes"
    res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.9

def _resolve_unknown(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Unknown question type — leave unresolved for review or LLM."""
    res.answer = None
    res.resolution_method = UNKNOWN_METHOD
    res.confidence = 0.0


# ── Resolver dispatch table ──────────────────────────────────────────────────

_RESOLVERS: dict[QuestionType, Any] = {
    QuestionType.FIRST_NAME: _resolve_first_name,
    QuestionType.LAST_NAME: _resolve_last_name,
    QuestionType.FULL_NAME: _resolve_full_name,
    QuestionType.PREFERRED_NAME: lambda r, p, o: _resolve_from_profile(r, p, o, "preferredName"),
    QuestionType.EMAIL: _resolve_email,
    QuestionType.PHONE: _resolve_phone,
    QuestionType.PHONE_COUNTRY: _resolve_phone_country,
    QuestionType.LOCATION: _resolve_location,
    QuestionType.CITY: _resolve_city,
    QuestionType.STATE: _resolve_state,
    QuestionType.COUNTRY: _resolve_country,
    QuestionType.ZIP: _resolve_zip,
    QuestionType.ADDRESS: _resolve_address,
    QuestionType.CURRENT_COMPANY: _resolve_current_company,
    QuestionType.CURRENT_TITLE: _resolve_current_title,
    QuestionType.YEARS_EXPERIENCE: _resolve_years_experience,
    QuestionType.LINKEDIN: _resolve_linkedin,
    QuestionType.GITHUB: _resolve_github,
    QuestionType.WEBSITE: _resolve_website,
    QuestionType.WORK_AUTHORIZED: _resolve_work_authorized,
    QuestionType.SPONSORSHIP_REQUIRED: _resolve_sponsorship_required,
    QuestionType.PERMANENT_WORK_AUTHORIZATION: _resolve_permanent_work_auth,
    QuestionType.CITIZENSHIP: _resolve_citizenship,
    QuestionType.EXPORT_CONTROL: _resolve_export_control,
    QuestionType.SECURITY_CLEARANCE_ELIGIBILITY: _resolve_clearance_eligibility,
    QuestionType.SECURITY_CLEARANCE_LEVEL: _resolve_clearance_level,
    QuestionType.GENDER: _resolve_gender,
    QuestionType.PRONOUNS: _resolve_pronouns,
    QuestionType.TRANSGENDER: _resolve_transgender,
    QuestionType.SEXUAL_ORIENTATION: _resolve_sexual_orientation,
    QuestionType.ETHNICITY_HISPANIC_LATINO: _resolve_ethnicity_hispanic,
    QuestionType.RACE: _resolve_race,
    QuestionType.VETERAN_STATUS: _resolve_veteran,
    QuestionType.DISABILITY: _resolve_disability,
    QuestionType.HOW_HEARD: _resolve_how_heard,
    QuestionType.RELOCATE: _resolve_relocate,
    QuestionType.SALARY: _resolve_salary,
    QuestionType.NOTICE_PERIOD: _resolve_notice_period,
    QuestionType.SMS_CONSENT: _resolve_sms_consent,
    QuestionType.ENGLISH_PROFICIENCY: _resolve_english_proficiency,
    QuestionType.PRIVACY_CONSENT: _resolve_privacy_consent,
    QuestionType.ACCURACY_CONFIRMATION: _resolve_accuracy_confirmation,
    QuestionType.BACKGROUND_CHECK: _resolve_background_check,
    QuestionType.COMPANY_HISTORY: _resolve_company_history,
    QuestionType.SCHOOL: _resolve_school,
    QuestionType.DEGREE: _resolve_degree,
    QuestionType.DISCIPLINE: lambda r, p, o: _resolve_from_profile(r, p, o, "discipline"),
    QuestionType.GPA: _resolve_gpa,
    QuestionType.TRANSCRIPT: _resolve_transcript,
}
