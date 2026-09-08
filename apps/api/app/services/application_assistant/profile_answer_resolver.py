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
from app.services.tracking_email import derive_contact_email
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
PROFILE_SCREENING_ANSWER = "PROFILE_SCREENING_ANSWER"
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


_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "you", "your", "do", "does", "did", "have",
    "has", "had", "will", "would", "can", "could", "to", "for", "of", "in",
    "on", "at", "this", "that", "and", "or", "if", "please", "select",
})


def _significant_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _find_user_approved_answer(question_text: str, answer_lib: list[dict[str, Any]]) -> str | None:
    """Look up a previously user-approved answer for a question that may be
    phrased slightly differently than when it was saved.

    Questions reaching here were classified/rephrased by an LLM (see
    error_normalizer.py), which isn't perfectly deterministic — the same
    underlying field can come back worded differently attempt to attempt.
    Exact string matching would silently miss the vast majority of repeat
    answers, defeating the entire point of saving one. Word-overlap matching
    is intentionally forgiving: a false-positive reuse of a similar-but-wrong
    saved answer is a much cheaper mistake than asking the candidate the same
    question forever and never actually applying self-healing to it.
    """
    if not answer_lib:
        return None
    target_words = _significant_words(question_text)
    if not target_words:
        return None

    best_entry = None
    best_score = 0.0
    for entry in answer_lib:
        if entry.get("verificationStatus") not in (None, "verified"):
            continue
        candidates = entry.get("questionVariants") or ([entry["normalizedKey"]] if entry.get("normalizedKey") else [])
        for variant in candidates:
            variant_words = _significant_words(str(variant))
            if not variant_words:
                continue
            overlap = len(target_words & variant_words) / max(len(target_words | variant_words), 1)
            if overlap > best_score:
                best_score = overlap
                best_entry = entry

    if best_entry is not None and best_score >= 0.5:
        return best_entry.get("value")
    return None


# ── Core resolver ────────────────────────────────────────────────────────────

def _match_preferred_office(options: list[str], profile: dict[str, Any]) -> str | None:
    """Pick an office from a posting's own list.

    Preference order, per the candidate's stated priority: their own metro
    (Seattle area) first, then any other US office, and finally the first
    option offered. Non-US offices are never chosen — applying to a role based
    outside the United States is explicitly out of scope.
    """
    NON_US = (
        "london", "toronto", "vancouver", "berlin", "munich", "dublin", "paris",
        "amsterdam", "singapore", "sydney", "tokyo", "bangalore", "hyderabad",
        "tel aviv", "warsaw", "krakow", "sao paulo", "mexico city", "remote - emea",
        "barcelona", "madrid", "milan", "zurich", "stockholm", "gurugram", "pune",
    )
    HOME = ("seattle", "bellevue", "redmond", "kirkland", "tacoma", "auburn", ", wa", "washington")

    usable = [o for o in options if o and not any(x in o.lower() for x in NON_US)]
    if not usable:
        return None
    for opt in usable:
        if any(h in opt.lower() for h in HOME):
            return opt
    return usable[0]


def resolve_answer(
    question_text: str,
    profile: dict[str, Any],
    options: list[str] | None = None,
    field_id: str = "",
    answer_lib: list[dict[str, Any]] | None = None,
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

    # An answer the candidate has explicitly saved for this exact question is the
    # most authoritative source there is, so it is consulted before any
    # type-based heuristic. This used to be missing entirely: resolve_answer is
    # what the form filler calls, but it never looked at profile
    # ["screeningAnswers"] — so questions the candidate HAD answered (age, the
    # truthfulness certification, English level, GPA) came back UNKNOWN, were
    # left blank in the browser, and the application was staged for review as
    # though the answer had never been given. Worse, a question like "Does your
    # salary fall within our estimated range?" was classified SALARY and
    # resolved to a dollar figure, which can never be selected in a Yes/No
    # dropdown, so the field stayed empty either way.
    from app.services.application_assistant.answer_classification import match_screening_answer

    screening = match_screening_answer(question_text, profile)
    if screening:
        _sid, saved = screening
        answer = str(saved).strip()
        # With a fixed option list, map the saved answer onto a real option —
        # writing a value the control doesn't offer leaves it blank in the DOM.
        if opts:
            matched = _match_option(opts, answer)
            if matched is None and len(opts) == 1:
                # Single-option acknowledgements ("I Acknowledge") carry no
                # choice; a saved "Yes" means take the only option there is.
                matched = opts[0]
            if matched is None:
                matched = _match_option(opts, "Yes") if answer.lower() in ("yes", "true", "y") else None
            if matched is None:
                matched = _match_option(opts, "No") if answer.lower() in ("no", "false", "n") else None
            if matched is not None:
                answer = matched
        if answer:
            resolution.answer = answer
            resolution.resolution_method = PROFILE_SCREENING_ANSWER
            resolution.confidence = 1.0
            resolution.profile_key = f"screeningAnswers.{_sid}"
            resolution.source_value = saved
            return resolution

    # "What is your preferred office location?" is a pick-from-their-list
    # question, so no stored string can answer it — the valid answers differ per
    # posting. Resolve it positionally against the options actually offered:
    # the candidate's own metro first, then any other US office. Observed live on
    # three Robinhood postings, whose office list (Menlo Park / New York) has no
    # Seattle entry and which therefore sat in review with nothing to review.
    if opts and re.search(r"preferred\s+office\s+location|which office|office (?:location )?preference",
                          question_text, re.I):
        preferred = _match_preferred_office(opts, profile)
        if preferred:
            resolution.answer = preferred
            resolution.resolution_method = DETERMINISTIC_RULE
            resolution.confidence = 0.9
        else:
            # Every office offered is outside the United States. Return
            # unresolved rather than falling through to the generic LOCATION
            # resolver, which would answer with the candidate's own city — a
            # value this dropdown does not offer, so it would either stay blank
            # or select something nonsensical.
            resolution.resolution_method = UNKNOWN_METHOD
        return resolution

    # A candidate's own prior approval outranks a fresh guess — but never for
    # sensitive factual fields (visa, citizenship, clearance, etc.), which must
    # always come from the authoritative profile, never a fuzzy-matched library
    # entry that could in principle have been saved against a differently-worded
    # (and differently-scoped) question.
    if not is_sensitive_factual(qtype) and answer_lib:
        approved = _find_user_approved_answer(question_text, answer_lib)
        if approved:
            resolution.answer = approved
            resolution.resolution_method = USER_OVERRIDE
            resolution.confidence = 0.9
            return resolution

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
    # Submit a taggable +career variant of the candidate's own email as the
    # form's contact address rather than the bare profile email, so
    # confirmations and replies are filterable without changing delivery.
    raw_email = profile.get("email")
    tagged_profile = profile if not raw_email else {**profile, "email": derive_contact_email(raw_email)}
    _resolve_from_profile(res, tagged_profile, opts, "email")

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
    # Profiles store one combined "location" string (e.g. "Auburn, WA") rather
    # than a separate "city" field, so a plain profile_key="city" lookup always
    # missed — this question type resolved to nothing on every real profile.
    city_fallback = None
    location = str(profile.get("location") or "").strip()
    if location:
        city_fallback = location.split(",")[0].strip() or None
    _resolve_from_profile(res, profile, opts, "city", fallback=city_fallback)

def _resolve_state(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    # Profiles store street-level detail under customFields (a separate
    # sub-object), not as flat top-level keys — a plain profile_key="state"
    # lookup always missed, same class of bug already fixed for city above.
    custom = profile.get("customFields") or {}
    state_fallback = str(custom.get("state") or "").strip() or "Washington"
    _resolve_from_profile(res, profile, opts, "state", fallback=state_fallback)

def _resolve_country(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "country", fallback="United States")

def _resolve_zip(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    custom = profile.get("customFields") or {}
    zip_fallback = str(custom.get("zip") or custom.get("postalCode") or "").strip() or None
    _resolve_from_profile(res, profile, opts, "zip", fallback=zip_fallback)

def _resolve_address(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    custom = profile.get("customFields") or {}
    addr_fallback = str(custom.get("addressLine1") or custom.get("street") or "").strip() or None
    _resolve_from_profile(res, profile, opts, "address", fallback=addr_fallback)

def _resolve_current_company(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "currentCompany")

def _resolve_current_title(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "currentTitle")

def _resolve_preferred_name(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    # Preferred name should always be a first/preferred name (e.g. "Akshay"),
    # NEVER a full name ("Akshay Borse").
    pref = profile.get("preferredName") or profile.get("firstName") or ""
    if pref:
        res.answer = str(pref).strip()
        res.resolution_method = PROFILE_EXACT
        res.profile_key = "preferredName"
        res.source_value = pref
        res.confidence = 1.0

def _resolve_linkedin(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "linkedin")

def _resolve_github(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "github")

def _resolve_website(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    # Check if question is asking for additional/other links
    q_low = res.question.lower()
    is_other_link = any(term in q_low for term in ["other link", "other website", "additional link", "additional website"])
    
    if is_other_link:
        # If candidate has explicit custom otherLinks, use it; otherwise leave empty/None
        custom_links = profile.get("otherLinks") or (profile.get("customFields") or {}).get("otherLinks")
        if custom_links:
            res.answer = str(custom_links).strip()
            res.resolution_method = PROFILE_EXACT
            res.profile_key = "otherLinks"
            res.source_value = custom_links
            res.confidence = 1.0
        else:
            # Explicitly blank: do NOT fall back to website or essay text
            res.answer = ""
            res.resolution_method = DETERMINISTIC_RULE
            res.confidence = 1.0
        return

    val = profile.get("portfolio") or profile.get("website")
    if val:
        res.answer = str(val)
        res.resolution_method = PROFILE_EXACT
        res.profile_key = "portfolio"
        res.source_value = val
        res.confidence = 1.0

def _resolve_years_experience(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    yoe = profile.get("yearsExperience", 8)
    try:
        yoe_int = int(yoe)
    except (ValueError, TypeError):
        yoe_int = 8

    if opts:
        # Check if this is a boolean Yes/No question (e.g. "Are you in your early career?")
        # A senior engineer with 8+ years of experience is not "early career".
        opt_lowers = [o.strip().lower() for o in opts]
        if set(opt_lowers) <= {"yes", "no", "n/a", "prefer not to answer"} and ("yes" in opt_lowers or "no" in opt_lowers):
            q_low = res.question.lower()
            if "early career" in q_low or "entry level" in q_low or "new grad" in q_low:
                # 8+ years is not early career
                matched = _match_option(opts, "No")
                res.answer = matched or "No"
            else:
                matched = _match_option(opts, "Yes") if yoe_int >= 3 else _match_option(opts, "No")
                res.answer = matched or ("Yes" if yoe_int >= 3 else "No")
            res.confidence = 1.0
            res.resolution_method = PROFILE_OPTION_MAPPING
            return

        for opt in opts:
            nums = [int(n) for n in re.findall(r"\d+", opt)]
            if len(nums) == 1:
                if "+" in opt or "more" in opt or "over" in opt or "greater" in opt:
                    if yoe_int >= nums[0]:
                        res.answer = opt
                        res.confidence = 1.0
                        res.resolution_method = PROFILE_OPTION_MAPPING
                        return
                elif nums[0] == yoe_int:
                    res.answer = opt
                    res.confidence = 1.0
                    res.resolution_method = PROFILE_OPTION_MAPPING
                    return
            elif len(nums) >= 2:
                if nums[0] <= yoe_int <= nums[1]:
                    res.answer = opt
                    res.confidence = 1.0
                    res.resolution_method = PROFILE_OPTION_MAPPING
                    return
        matched = _match_option(opts, str(yoe_int))
        res.answer = matched or opts[-1]
        res.confidence = 0.95
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = str(yoe_int)
        res.confidence = 1.0
        res.resolution_method = PROFILE_EXACT


# ── Work Authorization resolvers (the critical fixes) ────────────────────────

def _resolve_work_authorized(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    wa = _get_work_auth(profile)
    auth = wa["authorizedToWorkInUS"]
    if opts:
        if auth:
            yes_opt = None
            for opt in opts:
                opt_l = opt.lower()
                if opt_l.startswith("yes") or ("authorized" in opt_l and "not" not in opt_l and "unauthorized" not in opt_l) or "visa" in opt_l or "h-1b" in opt_l or "work authorization" in opt_l or "eligible" in opt_l or "source of right" in opt_l:
                    yes_opt = opt
                    break
            matched = yes_opt or _match_option(opts, "Yes")
            res.answer = matched or opts[0]
        else:
            matched = _match_option(opts, "No")
            res.answer = matched or "No"
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = "Yes" if auth else "No"
        res.resolution_method = PROFILE_EXACT
    res.profile_key = "workAuth.authorizedToWorkInUS"
    res.source_value = wa["authorizedToWorkInUS"]
    res.confidence = 1.0


def _resolve_sponsorship_required(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    wa = _get_work_auth(profile)
    requires = wa["requiresSponsorshipNowOrFuture"]
    if opts:
        if requires:
            # "Will you require sponsorship?" only tells us the candidate will
            # need it at some point — it says nothing about which specific
            # visa type they'd need, or whether they already hold one. Only
            # ever pick a visa-type-specific option (H-1B, F-1/CPT/OPT, etc.)
            # when the profile itself names that type; otherwise asserting
            # "I am on an H-1B visa" (or any other specific status) would be
            # a fabricated factual claim, not an honest "yes".
            visa_type = str(wa.get("authorizationType") or "").lower()
            specific_match = None
            if visa_type:
                for opt in opts:
                    if visa_type in opt.lower():
                        specific_match = opt
                        break
            if specific_match:
                res.answer = specific_match
            else:
                # Prefer a plain "Yes" option; only fall back to a
                # visa-specific-sounding option if that's genuinely all
                # that's offered, and even then prefer a generic catch-all
                # ("Other") over guessing a specific visa type.
                generic_yes = next((o for o in opts if o.strip().lower() == "yes"), None)
                other_opt = next((o for o in opts if o.strip().lower() == "other"), None)
                res.answer = generic_yes or other_opt or (_match_option(opts, "Yes") or "Yes")
        else:
            matched = _match_option(opts, "No")
            res.answer = matched or "No"
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = "Yes" if requires else "No"
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


def _resolve_sanctioned_countries(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """OFAC sanctioned-country citizenship/residency question (Cuba, Iran,
    North Korea, Syria, Crimea). No profile field tracks this because it's
    never true for any candidate in practice — answer "No" directly rather
    than routing through the unrelated US-citizenship question/resolver.
    """
    answer = "No"
    if opts:
        matched = _match_option(opts, answer)
        res.answer = matched or answer
        res.resolution_method = PROFILE_OPTION_MAPPING if matched else DETERMINISTIC_RULE
    else:
        res.answer = answer
        res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.95


def _resolve_government_conflict(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """"Have you been involved in procurement/contract award activities as a
    government employee?"-style conflict-of-interest checks. Same "No"
    answer already given for this exact concept elsewhere via screeningAnswers.
    """
    answer = "No"
    if opts:
        matched = _match_option(opts, answer)
        res.answer = matched or answer
        res.resolution_method = PROFILE_OPTION_MAPPING if matched else DETERMINISTIC_RULE
    else:
        res.answer = answer
        res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.95


def _resolve_ai_agent_disclosure(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """"Select Yes if you are an AI agent applying on behalf of a
    candidate"-style questions. Answered honestly: this genuinely is an AI
    agent submitting the application, so "Yes" is the factually correct
    answer, not a guess or a fabrication.
    """
    answer = "Yes"
    if opts:
        matched = _match_option(opts, answer)
        res.answer = matched or answer
        res.resolution_method = PROFILE_OPTION_MAPPING if matched else DETERMINISTIC_RULE
    else:
        res.answer = answer
        res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.98


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
        # Check all possible negative / none options
        for opt in opts:
            opt_lower = opt.lower()
            if any(phrase in opt_lower for phrase in [
                "not hold", "do not hold", "no active", "do not have", "no clearance", "none", "not applicable", "n/a", "no", "inactive"
            ]):
                res.answer = opt
                res.resolution_method = PROFILE_OPTION_MAPPING
                res.confidence = 1.0
                res.profile_key = "security.hasHeldUSSecurityClearance"
                res.source_value = sec["hasHeldUSSecurityClearance"]
                return
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

def _find_negative_option(opts: list[str], keyword: str) -> str | None:
    """Find a real option that answers 'no' about `keyword` (e.g. veteran,
    disability), for forms that phrase the standard EEOC negative response
    differently than our own default fallback text.

    _resolve_from_profile's fallback matching (pick_best_matching_option)
    requires a substring/synonym/exact match scoring >= 70 — a fixed default
    like "I am not a protected veteran" scores 0 against real-world phrasing
    like "No, I am not a veteran" (neither string contains the other), so the
    literal, non-matching fallback text was being recorded as the "resolved"
    answer even though it corresponds to no real option on the page — leaving
    the field permanently unfillable and unmatched at click time.
    """
    keyword = keyword.lower()
    for opt in opts:
        low = opt.lower()
        if keyword in low and re.search(r"\bno\b|\bnot\b", low):
            return opt
    return None


def _resolve_veteran(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    fallback = APPLICATION_FIELD_DEFAULTS.get("veteran", "I am not a protected veteran")
    _resolve_from_profile(res, profile, opts, "veteran", fallback=fallback)
    if opts and res.answer and res.answer.strip().lower() not in [o.strip().lower() for o in opts]:
        negative = _find_negative_option(opts, "veteran")
        if negative:
            res.answer = negative

def _resolve_disability(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    fallback = APPLICATION_FIELD_DEFAULTS.get("disability", "No, I don't have a disability")
    _resolve_from_profile(res, profile, opts, "disability", fallback=fallback)
    if opts and res.answer and res.answer.strip().lower() not in [o.strip().lower() for o in opts]:
        negative = _find_negative_option(opts, "disab")
        if negative:
            res.answer = negative


def _resolve_first_gen_professional(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """"First-generation professional" is a voluntary self-identification
    question about the candidate's own family/career history, not a fact the
    profile records — answering "Yes" or "No" without knowing the truth would
    be a fabrication. Declining is the only honest default absent explicit
    profile data.
    """
    value = profile.get("firstGenerationProfessional")
    if value is not None and str(value).strip():
        _resolve_from_profile(res, profile, opts, "firstGenerationProfessional")
        return
    decline = _find_decline_option(opts) if opts else None
    res.answer = decline or ("I don't wish to answer" if not opts else opts[-1])
    res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.9


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


def _resolve_company_familiarity(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """"How familiar were you with [Company] before applying?"-style survey
    question. The most honest answer for an application sourced through
    automated job discovery is the option describing learning about the
    company through the posting itself, not a claim of prior familiarity we
    have no basis for.
    """
    default = "I learned about the company through this job posting"
    if opts:
        posting_opt = next((o for o in opts if re.search(r"job\s*posting|recruiter", o, re.IGNORECASE)), None)
        heard_opt = next((o for o in opts if re.search(r"heard.*didn.?t\s*know|somewhat\s*familiar", o, re.IGNORECASE)), None)
        res.answer = posting_opt or heard_opt or opts[0]
        res.resolution_method = DETERMINISTIC_RULE
    else:
        res.answer = default
        res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.85


def _resolve_relocate(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    # "Are you willing to relocate?" and "Will you REQUIRE relocation
    # (assistance)?" are opposite-direction questions that both match the
    # same "relocat" classifier pattern — a candidate open to relocating
    # does NOT require the company to relocate them, so blindly answering
    # "Yes" to both is wrong for the "require" phrasing specifically.
    q_low = (res.question or "").lower()
    requires_relocation_assistance = bool(re.search(r"\brequire\b.{0,15}relocat", q_low))
    fallback = "No" if requires_relocation_assistance else "Yes"
    _resolve_from_profile(res, profile, opts, "relocate", fallback=fallback)

def _resolve_work_arrangement(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Hybrid / remote / onsite schedule questions — the candidate is open to any."""
    stored = str(profile.get("workArrangement") or "").strip()
    if not opts:
        res.answer = stored or "Yes"
        res.resolution_method = PROFILE_EXACT if stored else DETERMINISTIC_RULE
        res.confidence = 0.9 if stored else 0.7
        return

    # Prefer an explicit "open to anything" option when the form offers one.
    for keyword in ("flexible", "no preference", "open to all", "open to any", "either", "any of the above"):
        matched = _match_option(opts, keyword)
        if matched:
            res.answer = matched
            res.resolution_method = PROFILE_OPTION_MAPPING
            res.confidence = 0.95
            return

    if stored:
        matched = _match_option(opts, stored)
        if matched:
            res.answer = matched
            res.resolution_method = PROFILE_OPTION_MAPPING
            res.confidence = 0.9
            return

    # A plain Yes/No question ("are you open to hybrid, 3 days/week?") — being
    # open to all arrangements means yes to whichever specific one is asked.
    matched_yes = _match_option(opts, "Yes")
    if matched_yes:
        res.answer = matched_yes
        res.resolution_method = DETERMINISTIC_RULE
        res.confidence = 0.9
        return

    # A genuine single-choice among Remote/Hybrid/Onsite with no umbrella
    # option isn't answerable from "open to all" alone — leave it for review
    # rather than guessing which one this specific listing wants to hear.

def _resolve_timezone_availability(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """"Are you ok working Eastern/Central Time?"-style questions — the
    candidate is generally flexible on core-hours overlap, same spirit as
    being open to any work arrangement.
    """
    answer = "Yes"
    if opts:
        matched = _match_option(opts, answer)
        res.answer = matched or answer
        res.resolution_method = PROFILE_OPTION_MAPPING if matched else DETERMINISTIC_RULE
    else:
        res.answer = answer
        res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.85

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
        # Some forms (observed on Sezzle) offer bare CEFR codes (A1-C2)
        # instead of descriptive text — "Fluent"/"Professional"/"Native"
        # share no substring with "C2", so the descriptive-text match below
        # always missed and left the field unresolved. C2 is the correct
        # CEFR level for a fluent/native-equivalent self-assessment.
        cefr_opts = {o.strip().upper() for o in opts}
        if cefr_opts & {"A1", "A2", "B1", "B2", "C1", "C2"}:
            matched = _match_option(opts, "C2") or _match_option(opts, "C1")
            res.answer = matched or target
        else:
            matched = _match_option(opts, target) or _match_option(opts, "Professional") or _match_option(opts, "Native")
            res.answer = matched or target
    else:
        res.answer = target
    res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.95

def _resolve_privacy_consent(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    target = "I agree"
    if opts:
        res.answer = _match_option(opts, "I agree") or _match_option(opts, "Agree") or _match_option(opts, "Yes") or _match_option(opts, "I acknowledge") or _match_option(opts, "Accept") or opts[0]
    else:
        res.answer = target
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

def _resolve_test_score(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    if opts:
        for opt in opts:
            opt_l = opt.lower()
            if any(k in opt_l for k in ["n/a", "not applicable", "did not take", "none", "no", "not taken", "i did not take", "i do not have", "0"]):
                res.answer = opt
                res.confidence = 1.0
                res.resolution_method = PROFILE_OPTION_MAPPING
                return
        res.answer = opts[0]
        res.confidence = 0.9
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = "N/A"
        res.confidence = 1.0
        res.resolution_method = PROFILE_EXACT

def _resolve_location_confirmation(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    q_low = (res.question or "").lower()
    profile_state = (profile.get("state") or "Washington").lower()
    profile_city = (profile.get("city") or "Auburn").lower()

    # Check if question is asking about living in US / candidate's region
    is_asking_us = any(k in q_low for k in ["united states", "u.s.", "usa", "in the us", "within the us", "north america"])
    has_candidate_state = profile_state in q_low or " wa " in q_low or "(wa)" in q_low

    if opts:
        # If options are country/state names
        for opt in opts:
            opt_l = opt.lower()
            if "united states" in opt_l or "usa" in opt_l or "u.s." in opt_l or profile_state in opt_l or profile_city in opt_l:
                res.answer = opt
                res.confidence = 1.0
                res.resolution_method = PROFILE_OPTION_MAPPING
                return

        # If options are Yes/No
        if is_asking_us and not has_candidate_state and "following states" not in q_low and "these states" not in q_low:
            res.answer = _match_option(opts, "Yes") or "Yes"
        elif has_candidate_state:
            res.answer = _match_option(opts, "Yes") or "Yes"
        else:
            # Question asks if living in a list of states that does NOT include Washington
            res.answer = _match_option(opts, "No") or "No"

        res.confidence = 1.0
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = "No" if not (is_asking_us or has_candidate_state) else "Yes"
        res.confidence = 1.0
        res.resolution_method = PROFILE_EXACT

def _resolve_tech_stack_experience(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    if opts:
        for opt in opts:
            opt_l = opt.lower()
            if any(s in opt_l for s in ["both", "all of the above", "python", "golang", "go", "ruby", "distributed"]):
                res.answer = opt
                res.confidence = 1.0
                res.resolution_method = PROFILE_OPTION_MAPPING
                return
        res.answer = opts[0]
        res.confidence = 0.9
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = "Python, Go, TypeScript, React"
        res.confidence = 1.0
        res.resolution_method = PROFILE_EXACT

def _resolve_preferred_language(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    default = "Python"
    if opts:
        res.answer = _match_option(opts, default) or default
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = default
        res.resolution_method = PROFILE_EXACT
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
    QuestionType.PREFERRED_NAME: _resolve_preferred_name,
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
    QuestionType.SANCTIONED_COUNTRIES: _resolve_sanctioned_countries,
    QuestionType.GOVERNMENT_CONFLICT: _resolve_government_conflict,
    QuestionType.AI_AGENT_DISCLOSURE: _resolve_ai_agent_disclosure,
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
    QuestionType.FIRST_GEN_PROFESSIONAL: _resolve_first_gen_professional,
    QuestionType.HOW_HEARD: _resolve_how_heard,
    QuestionType.COMPANY_FAMILIARITY: _resolve_company_familiarity,
    QuestionType.RELOCATE: _resolve_relocate,
    QuestionType.WORK_ARRANGEMENT: _resolve_work_arrangement,
    QuestionType.TIMEZONE_AVAILABILITY: _resolve_timezone_availability,
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
    QuestionType.TEST_SCORE: _resolve_test_score,
    QuestionType.LOCATION_CONFIRMATION: _resolve_location_confirmation,
    QuestionType.TECH_STACK_EXPERIENCE: _resolve_tech_stack_experience,
    QuestionType.PREFERRED_LANGUAGE: _resolve_preferred_language,
    QuestionType.TRANSCRIPT: _resolve_transcript,
}
