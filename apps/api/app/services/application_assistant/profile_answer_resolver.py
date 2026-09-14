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


def _is_yes_no_options(options: list[str]) -> bool:
    """True when the control offers only a yes/no style choice."""
    if not options:
        return False
    normalized = {o.strip().lower() for o in options if o.strip()}
    if not normalized or len(normalized) > 3:
        return False
    allowed = {"yes", "no", "true", "false", "n/a", "prefer not to answer",
               "decline to answer", "i decline to answer"}
    return normalized.issubset(allowed) and bool(normalized & {"yes", "no"})


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

def _match_yes_no_sentence_option(options: list[str], answer: str) -> str | None:
    """Map a yes/no answer onto sentence-form options.

    Returns None unless exactly one option expresses the wanted polarity, so an
    ambiguous list is left for the caller rather than guessed at.
    """
    want = answer.strip().lower()
    if want in ("yes", "true", "y"):
        positive = True
    elif want in ("no", "false", "n"):
        positive = False
    else:
        return None

    NEGATIVE = (" never ", " never", "have not", "haven't", "do not", "don't",
                "did not", "didn't", "none of", "no, ", "not applicable")
    negatives, positives = [], []
    for opt in options:
        padded = f" {opt.strip().lower()} "
        if any(marker in padded for marker in NEGATIVE):
            negatives.append(opt)
        else:
            positives.append(opt)

    wanted = positives if positive else negatives
    return wanted[0] if len(wanted) == 1 else None


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
    # A compound "city and state" ask must be answered in full before the
    # type-based resolvers see it — they each return one component and silently
    # drop the rest.
    compound = _compound_location_answer(question_text, profile)
    if compound and not opts:
        resolution.answer = compound
        resolution.question_type = QuestionType.LOCATION.value
        resolution.resolution_method = PROFILE_EXACT
        resolution.profile_key = "city+state"
        resolution.confidence = 1.0
        return resolution

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
            if matched is None:
                # Some employers phrase the choices as full sentences rather
                # than Yes/No — Robinhood's "Have you ever worked here?" offers
                # "I have never worked at Robinhood" and four affirmative
                # variants, none of which contains the word "no". A saved "No"
                # was returned verbatim, could not be selected, and left a
                # required field blank. Map a yes/no answer onto the option that
                # actually expresses it.
                matched = _match_yes_no_sentence_option(opts, answer)
            if matched is not None:
                answer = matched
            elif answer.lower() in ("yes", "no", "true", "false", "y", "n"):
                # The saved answer names no option this control offers, so
                # returning it would write a value that can never be selected.
                # Fall through to the type-specific resolver, which knows how to
                # read this particular question's option list.
                answer = ""
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

    # Greenhouse's structured employment rows are identified by their element id
    # (company-name-0, start-date-month-1, ...), not by a question type, so they
    # are resolved before the type dispatch below ever sees them.
    employment = _employment_field(field_id, question_text)
    if employment:
        _resolve_employment_history(resolution, profile, opts, employment[0], employment[1])
        resolution.question_type = QuestionType.UNKNOWN.value
        return resolution

    education = _education_field(field_id, question_text)
    if education:
        _resolve_education_history(resolution, profile, opts, education[0], education[1])
        return resolution

    # A Yes/No that states a years-of-experience threshold has exactly one
    # truthful answer, and which one depends on the direction the threshold
    # points. This is checked ahead of the type dispatch because the same
    # question arrives under several types (YEARS_EXPERIENCE for "at least 5
    # years of experience", TECH_STACK_EXPERIENCE for "at most 5 years of
    # professional experience"), and each of those resolvers otherwise answers
    # "Yes" to anything. Observed live: a nine-year engineer told Reddit he had
    # "fewer than five years of experience architecting and scaling distributed
    # backend systems" — untrue, and a screening knockout.
    threshold = _years_threshold(question_text) if _is_yes_no_options(opts) else None
    if threshold is not None and re.search(r"experience", question_text, re.I):
        try:
            candidate_years = float(str(profile.get("yearsExperience", "")).strip())
        except (TypeError, ValueError):
            candidate_years = None
        if candidate_years is not None:
            years, asks_for_below = threshold
            truthful = "Yes" if ((candidate_years < years) == asks_for_below) else "No"
            resolution.answer = _match_option(opts, truthful) or truthful
            resolution.resolution_method = PROFILE_EXACT
            resolution.profile_key = "yearsExperience"
            resolution.source_value = profile.get("yearsExperience")
            resolution.confidence = 1.0
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

_CITY_WORD = "city"
_STATE_WORD = "state"


def _compose_location(profile: dict, want_country: bool) -> str:
    """Build "Seattle, Washington[, United States]" from the profile."""
    custom = profile.get("customFields") or {}
    city = str(profile.get("city") or custom.get("city") or "").strip()
    state = str(profile.get("state") or custom.get("state") or "").strip()
    country = str(profile.get("country") or custom.get("country") or "United States").strip()
    parts = [p for p in (city, state) if p]
    if want_country and country:
        parts.append(country)
    return ", ".join(parts)


def _compound_location_answer(question: str, profile: dict) -> str | None:
    """Answer questions that ask for city AND state (and sometimes country).

    "In which city and state do you permanently reside?" classifies as STATE,
    whose resolver returns "Washington" alone — so four submitted applications
    answered a city-and-state question with just the state, dropping half the
    answer. Detect the compound ask and give every part that was requested.
    """
    q = (question or "").lower()
    if _CITY_WORD not in q or _STATE_WORD not in q:
        return None
    # "Which state ... in the city of X" style questions still want one value;
    # require the two words to be asked together as a pair.
    if not any(
        pat in q
        for pat in ("city and state", "city, state", "city & state",
                    "city and the state", "state and city", "city/state")
    ):
        return None
    want_country = "country" in q
    composed = _compose_location(profile, want_country)
    return composed or None


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
    # "streetAddress" is what the Profile page writes, and it was missing from
    # this lookup entirely — so a profile that genuinely held the candidate's
    # address still answered nothing, and every posting with a required mailing
    # address was staged for review.
    custom = profile.get("customFields") or {}
    addr_fallback = str(
        profile.get("streetAddress")
        or custom.get("address")
        or custom.get("addressLine1")
        or custom.get("street")
        or ""
    ).strip() or None
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

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
    "twenty": 20,
}

# "Do you have fewer than five years of X?" and "Do you have at least five years
# of X?" are the same threshold asked in opposite directions, and the truthful
# Yes/No is opposite too.
_BELOW_THRESHOLD_PATTERNS = (
    r"fewer\s+than", r"less\s+than", r"under\s+\d", r"below\s+\d",
    r"no\s+more\s+than", r"at\s+most", r"or\s+fewer", r"or\s+less",
)
_ABOVE_THRESHOLD_PATTERNS = (
    r"at\s+least", r"more\s+than", r"greater\s+than", r"minimum\s+of",
    r"\d\s*\+", r"or\s+more", r"over\s+\d",
)


def _is_yes_no_options(opts: list[str]) -> bool:
    """Whether an option list is a plain Yes/No (possibly with a decline)."""
    lowered = {o.strip().lower() for o in opts if o and o.strip()}
    if not lowered:
        return False
    return lowered <= {"yes", "no", "n/a", "prefer not to answer", "decline to answer"} and bool(
        lowered & {"yes", "no"}
    )


def _years_threshold(question: str) -> tuple[int, bool] | None:
    """Parse "(fewer|at least) than N years" as (N, asks_for_below).

    Returns None when the question states no numeric threshold, in which case
    there is nothing to compare and the caller keeps its existing behaviour.
    """
    text = (question or "").lower()
    m = re.search(r"(\d+)\s*\+?(?:\s+or\s+(?:more|fewer|less))?\s*years?", text)
    threshold: int | None = int(m.group(1)) if m else None
    if threshold is None:
        # Spelled-out counts ("fewer than five years"). Compared token by
        # token rather than by regex so the word has to be the count itself,
        # not a fragment of a longer word.
        words = re.findall(r"[a-z]+", text)
        for position, token in enumerate(words[:-1]):
            if token in _NUMBER_WORDS and words[position + 1].startswith("year"):
                threshold = _NUMBER_WORDS[token]
                break
    if threshold is None:
        return None
    below = any(re.search(pat, text) for pat in _BELOW_THRESHOLD_PATTERNS)
    above = any(re.search(pat, text) for pat in _ABOVE_THRESHOLD_PATTERNS)
    if below and not above:
        return threshold, True
    if above and not below:
        return threshold, False
    return None


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


# "Which country/region ...?" phrasings. These are NOT yes/no questions, and the
# profile records no country of citizenship at all, so there is no honest answer
# to give — the only options are leave it blank (job goes to review) or invent a
# country. A Twitch application had "In which country/region do you have
# citizenship?" answered "Lebanon" at 0.00 confidence, because the yes/no
# resolver below produced "No" and that got fuzzy-matched into the country
# dropdown. A fabricated country of citizenship on a real submission is a
# serious misstatement, so these questions are refused outright.
_COUNTRY_VALUED_QUESTION = re.compile(
    r"(which|what)\s+(country|region|countries|nation)"
    r"|country\s*/\s*region\s+(do|of)"
    r"|country\s+of\s+(citizenship|legal\s+permanent\s+residence|residence|nationality)"
    r"|provide\s+your\s+country",
    re.I,
)


def _asks_for_a_country_name(question: str) -> bool:
    return bool(_COUNTRY_VALUED_QUESTION.search(question or ""))


def _resolve_citizenship(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Never claim US citizenship unless profile confirms it."""
    if _asks_for_a_country_name(res.question):
        # Leave unanswered: the profile has no country of citizenship, and a
        # yes/no answer forced into a country list produces a fabricated one.
        res.answer = None
        res.confidence = 0.0
        res.resolution_method = UNKNOWN_METHOD
        res.blocking_errors.append(
            "Country of citizenship is not recorded in the profile; "
            "refusing to select a country rather than state a false one."
        )
        return
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

        # The profile holds a broad category ("Asian"). Some employers offer only
        # narrower subgroups — East Asian / South Asian / Southeast Asian — and
        # substring matching happily returned the first of them, putting a
        # specific ancestry claim the candidate never made onto a real
        # application. When the profile value fits more than one option it is
        # ambiguous against this particular list, so decline instead of picking
        # one. A single match is still taken, which keeps the standard EEOC
        # wording ("Asian (Not Hispanic or Latino)") resolving normally.
        val_word = re.compile(rf"\b{re.escape(val.strip())}\b", re.I) if val.strip() else None
        fitting = [o for o in safe_opts if val_word and val_word.search(o)] if val_word else []
        if len(fitting) == 1:
            res.answer = fitting[0]
        elif len(fitting) > 1:
            decline = _find_decline_option(safe_opts)
            res.answer = decline or ""
            if not res.answer:
                res.resolution_method = UNKNOWN_METHOD
                res.profile_key = "raceEthnicity"
                res.source_value = val
                res.confidence = 0.0
                return
        else:
            # No option names the candidate's race as a whole word. The generic
            # substring matcher must not be used as a fallback here: asked for
            # "Asian" against a list offering "Caucasian", it matches on the
            # shared letters and states a race the candidate is not. Decline
            # instead, and if the form offers no decline leave it unresolved so
            # the application is staged rather than answered wrongly.
            decline = _find_decline_option(safe_opts)
            if decline:
                res.answer = decline
            else:
                res.answer = ""
                res.resolution_method = UNKNOWN_METHOD
                res.profile_key = "raceEthnicity"
                res.source_value = val
                res.confidence = 0.0
                return
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

def _find_negative_option(opts: list[str], keyword: str | tuple[str, ...]) -> str | None:
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

    `keyword` accepts more than one synonym because the real negative option
    does not always restate the question's own noun: Robinhood's veteran
    question offers "I have never served in the military" as its negative
    answer, which contains neither "veteran" nor "not" - confirmed against
    the board's live DOM (its 7 options are: active duty / national guard or
    reserve / never served in the military / protected veteran /
    non-protected veteran / multiple categories / decline to answer).
    "never" is included in the negation set for exactly that phrasing.
    """
    keywords = (keyword,) if isinstance(keyword, str) else keyword
    keywords = tuple(k.lower() for k in keywords)
    for opt in opts:
        low = opt.lower()
        if any(k in low for k in keywords) and re.search(r"\bno\b|\bnot\b|\bnever\b|\bnone\b", low):
            return opt
    return None


def _resolve_veteran(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    fallback = APPLICATION_FIELD_DEFAULTS.get("veteran", "I am not a protected veteran")
    _resolve_from_profile(res, profile, opts, "veteran", fallback=fallback)
    if opts and res.answer and res.answer.strip().lower() not in [o.strip().lower() for o in opts]:
        negative = _find_negative_option(opts, ("veteran", "military", "served"))
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
        matched = (_match_option(opts, default)
                   or _match_option(opts, "LinkedIn")
                   or _match_option(opts, "Job Board")
                   or _match_option(opts, "Career Site")
                   or _match_option(opts, "Company Website")
                   or _match_option(opts, "Online")
                   or _match_option(opts, "Other"))
        res.answer = matched or opts[0]
        res.resolution_method = PROFILE_OPTION_MAPPING if matched else DETERMINISTIC_RULE
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

    Also handles "Have you used X?" (Robinhood) / "Are you familiar with X?"
    (Twitch) — product-use or brand-awareness questions that have Yes/No
    options. The candidate does use these products, so Yes is truthful.
    """
    q_low = (res.question or "").lower()
    is_product_use = bool(re.search(r"have\s+you\s+used\b|are\s+you\s+familiar\s+with", q_low))
    if is_product_use:
        if opts:
            matched = _match_option(opts, "Yes")
            res.answer = matched or "Yes"
            res.resolution_method = PROFILE_OPTION_MAPPING if matched else DETERMINISTIC_RULE
        else:
            res.answer = "Yes"
            res.resolution_method = DETERMINISTIC_RULE
        res.confidence = 0.9
        return
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
    if requires_relocation_assistance:
        # Not asking the company to pay for a move commits the candidate to
        # nothing, so "No" stays a safe default here.
        _resolve_from_profile(res, profile, opts, "relocateAssistance", fallback="No")
        return
    # Willingness to move is a promise on a real application, so it comes from
    # the profile or not at all — never a hardcoded "Yes".
    _resolve_from_profile(res, profile, opts, "relocate")

# Wording that turns a work-arrangement question into a commitment about being
# in a particular place, rather than a preference between schedules.
_PLACE_COMMITMENT_PATTERNS = (
    r"relocat",
    r"commut",
    r"come\s+(?:in\s+)?on-?site",
    r"hq\s+(?:is\s+)?in",
    r"headquarter",
    r"based\s+(?:out\s+)?in",
    r"office\s+(?:is\s+)?(?:located\s+)?in",
    r"in-?\s?office\s+in",
    r"willing\s+to\s+(?:move|relocate)",
)


def _asks_to_commit_to_a_place(question: str, profile: dict) -> bool:
    """Whether a work-arrangement question really asks the candidate to commit
    to being somewhere they do not live.

    "Are you open to a hybrid schedule, three days a week?" is a preference, and
    a candidate open to any arrangement can answer it. "Our HQ is in San Mateo
    and this role is not remote — are you able to come onsite as required?" is a
    relocation commitment. Answering that "Yes" for a candidate whose profile
    says Seattle puts a promise on a real application that they never made, so
    it belongs in review instead.
    """
    text = (question or "").lower()
    if not any(re.search(pat, text) for pat in _PLACE_COMMITMENT_PATTERNS):
        return False
    # A question naming the candidate's own city or state is asking about
    # somewhere they already are, so it stays answerable.
    for key in ("city", "state", "location"):
        raw = str(profile.get(key) or "").strip().lower()
        head = raw.split(",")[0].strip()
        if len(head) > 2 and head in text:
            return False
    return True


def _resolve_work_arrangement(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Hybrid / remote / onsite schedule questions — the candidate is open to any."""
    if _asks_to_commit_to_a_place(res.question, profile):
        # This is a location commitment, not a schedule preference, so it is
        # answered from the candidate's recorded relocation stance rather than
        # from "open to any arrangement". With no stance on file it stays
        # unresolved and goes to review — the candidate decides whether they
        # will move for a role, not the resolver.
        _resolve_relocate(res, profile, opts)
        if not res.answer:
            res.resolution_method = UNKNOWN_METHOD
        return
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
    # "Does your salary expectation fall within our estimated range?" is a
    # yes/no question that merely mentions salary. Resolving it to the
    # candidate's figure writes "$140,000" into a Yes/No control, which can
    # never be selected, so the field stayed empty and staged the application.
    # Answer the question that was actually asked: the posted range is what the
    # candidate is applying against, so "yes" is the honest reply unless the
    # profile records a figure above it — which we cannot compare without the
    # range, so we do not guess beyond the plain yes.
    q_low = (res.question or "").lower()
    asks_within_range = any(
        k in q_low for k in ("fall within", "within our", "within the range",
                             "within this range", "align with the range",
                             "comfortable with the range", "within our estimated",
                             "accept the listed salary range", "accept the salary range")
    )
    if asks_within_range:
        matched = _match_option(opts, "Yes") if opts else None
        res.answer = matched or "Yes"
        res.resolution_method = PROFILE_OPTION_MAPPING if matched else DETERMINISTIC_RULE
        res.profile_key = "salaryExpectations"
        res.source_value = profile.get("salaryExpectations")
        res.confidence = 0.9
        return
    _resolve_from_profile(res, profile, opts, "salaryExpectations", fallback="Open / Negotiable")

def _resolve_notice_period(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    q_low = (res.question or "").lower()
    if any(k in q_low for k in ("job search", "active are you", "search activity", "search status")):
        if opts:
            matched = (_match_option(opts, "Actively looking")
                       or _match_option(opts, "Open to opportunities")
                       or _match_option(opts, "Ready to interview")
                       or _match_option(opts, "Active"))
            res.answer = matched or opts[0]
            res.resolution_method = PROFILE_OPTION_MAPPING if matched else DETERMINISTIC_RULE
        else:
            res.answer = "Actively looking"
            res.resolution_method = DETERMINISTIC_RULE
        res.confidence = 0.95
        return

    val = profile.get("noticePeriod") or "2 weeks"
    if opts:
        matched = (_match_option(opts, str(val))
                   or _match_option(opts, "2 weeks")
                   or _match_option(opts, "2 weeks from offer")
                   or _match_option(opts, "Within 2 weeks")
                   or _match_option(opts, "Immediately")
                   or _match_option(opts, "Immediate"))
        res.answer = matched or opts[0]
        res.resolution_method = PROFILE_OPTION_MAPPING if matched else DETERMINISTIC_RULE
    else:
        res.answer = str(val)
        res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.95


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

# ── Greenhouse structured employment history ─────────────────────────────────
# Greenhouse's "Employment" block is not a free-text question: it is a fixed set
# of required inputs (Company name / Title / Start date month+year / End date
# month+year) repeated per row, with stable ids ending in the row index —
# company-name-0, title-0, start-date-month-0, end-date-year-1, and so on.
# Nothing here resolved them, so every posting that turned that block on stalled
# in review with "Required field 'Title*' is empty" even though the candidate's
# own profile carries the whole history. These answers are read straight off
# profile["workExperience"]; when the profile has no row at that index the field
# is left unresolved rather than filled with a plausible-looking guess.

_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

_EMPLOYMENT_FIELD_ID = re.compile(
    r"^(company-name|title|start-date-month|start-date-year|end-date-month|end-date-year)-+(\d+)$",
    re.I,
)

# Greenhouse's education block uses its own id shape (school--0, degree--0,
# start-year--1, ...). It is resolved positionally like the employment block so
# a second degree fills row 1 rather than repeating row 0.
_EDUCATION_FIELD_ID = re.compile(
    r"^(school|degree|discipline|start-year|end-year|start-month|end-month)-+(\d+)$",
    re.I,
)


def _employment_field(field_id: str, question: str) -> tuple[str, int] | None:
    """Identify a Greenhouse employment-block input as (kind, row index)."""
    m = _EMPLOYMENT_FIELD_ID.match((field_id or "").strip())
    if not m:
        return None
    kind = m.group(1).lower()
    # The label has to agree with the id: an unrelated custom question that
    # happens to be called "title-0" must not be answered with an employer name.
    q = (question or "").strip().lower().rstrip("*").strip()
    expected = {
        "company-name": ("company name", "company"),
        "title": ("title", "job title"),
        "start-date-month": ("start date month",),
        "start-date-year": ("start date year",),
        "end-date-month": ("end date month",),
        "end-date-year": ("end date year",),
    }[kind]
    if q and not any(q.startswith(e) for e in expected):
        return None
    return kind, int(m.group(2))


def _education_field(field_id: str, question: str) -> tuple[str, int] | None:
    """Identify a Greenhouse education-block input as (kind, row index)."""
    m = _EDUCATION_FIELD_ID.match((field_id or "").strip())
    if not m:
        return None
    kind = m.group(1).lower()
    # The label has to agree with the id, for the same reason the employment
    # block checks: a custom question that happens to be called "degree--0"
    # must not be answered with the candidate's degree.
    q = (question or "").strip().lower().rstrip("*").strip()
    expected = {
        "school": ("school", "university", "college", "institution"),
        "degree": ("degree",),
        "discipline": ("discipline", "major", "field of study"),
        "start-year": ("start date year", "start year"),
        "end-year": ("end date year", "end year", "graduation year"),
        "start-month": ("start date month", "start month"),
        "end-month": ("end date month", "end month"),
    }[kind]
    if q and not any(q.startswith(e) for e in expected):
        return None
    return kind, int(m.group(2))


def _education_entries(profile: dict) -> list[dict[str, Any]]:
    """The candidate's education rows, most recent degree first.

    Falls back to the flat school/degree/discipline profile keys so a profile
    that only ever recorded a single degree still answers row 0.
    """
    entries = profile.get("education")
    if isinstance(entries, list) and entries:
        return [e for e in entries if isinstance(e, dict)]
    flat = {
        "school": profile.get("school"),
        "degree": profile.get("degree"),
        "discipline": profile.get("discipline"),
    }
    return [flat] if any(str(v or "").strip() for v in flat.values()) else []


def _resolve_education_history(
    res: AnswerResolution, profile: dict, opts: list[str], kind: str, index: int
) -> None:
    entries = _education_entries(profile)
    if index >= len(entries):
        return
    entry = entries[index] or {}

    if kind in ("school", "degree", "discipline"):
        value = str(entry.get(kind) or "").strip()
    else:
        source = entry.get("startDate") if kind.startswith("start") else entry.get("endDate")
        raw = str(source or "").strip()
        parts = _split_month_year(raw)
        if parts:
            value = parts[0] if kind.endswith("month") else parts[1]
        elif kind.endswith("year") and re.fullmatch(r"\d{4}", raw):
            # Education rows are commonly recorded as a bare year.
            value = raw
        else:
            value = ""

    if not value:
        return

    if opts:
        matched = _match_option(opts, value)
        if matched is None:
            return
        res.answer = matched
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = value
        res.resolution_method = PROFILE_EXACT
    res.profile_key = f"education[{index}].{kind}"
    res.source_value = value
    res.confidence = 1.0


def _split_month_year(value: str) -> tuple[str, str] | None:
    """Split a profile date like "09/2025" into ("September", "2025")."""
    raw = str(value or "").strip()
    m = re.match(r"^(\d{1,2})[/\-](\d{4})$", raw)
    if m:
        month_num = int(m.group(1))
        if 1 <= month_num <= 12:
            return _MONTH_NAMES[month_num - 1], m.group(2)
        return None
    m = re.match(r"^(\d{4})[/\-](\d{1,2})$", raw)
    if m:
        month_num = int(m.group(2))
        if 1 <= month_num <= 12:
            return _MONTH_NAMES[month_num - 1], m.group(1)
    return None


def _resolve_employment_history(
    res: AnswerResolution, profile: dict, opts: list[str], kind: str, index: int
) -> None:
    history = profile.get("workExperience") or []
    if not isinstance(history, list) or index >= len(history):
        return
    entry = history[index] or {}
    currently = bool(entry.get("currentlyEmployed"))

    value: str = ""
    if kind == "company-name":
        value = str(entry.get("company") or "").strip()
    elif kind == "title":
        value = str(entry.get("jobTitle") or entry.get("title") or "").strip()
    else:
        if kind.startswith("end-date") and currently:
            # The row is the candidate's current job, so there is no end date to
            # give. Greenhouse's own "Current role" checkbox is the truthful way
            # to say that (ticking it disables both end-date inputs), and the
            # executor ticks it; inventing an end date here would put a false
            # employment record on a real application.
            return
        source = entry.get("startDate") if kind.startswith("start-date") else entry.get("endDate")
        parts = _split_month_year(source)
        if not parts:
            return
        value = parts[0] if kind.endswith("month") else parts[1]

    if not value:
        return

    if opts:
        matched = _match_option(opts, value)
        if matched is None:
            return
        res.answer = matched
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = value
        res.resolution_method = PROFILE_EXACT
    res.profile_key = f"workExperience[{index}].{kind}"
    res.source_value = value
    res.confidence = 1.0


# Subsidiaries whose application forms ask about the *parent* company, so a
# question naming the parent has to be checked against the candidate's real
# employment history rather than assumed to be a stranger-company question.
_EMPLOYER_ALIASES: dict[str, tuple[str, ...]] = {
    "amazon": ("amazon", "aws", "amazon web services", "twitch", "audible", "zappos", "whole foods"),
    "microsoft": ("microsoft", "msft", "linkedin", "github", "activision"),
    "google": ("google", "alphabet", "youtube"),
    "meta": ("meta", "facebook", "instagram", "whatsapp"),
}


def _prior_employers(profile: dict) -> set[str]:
    """Every employer name the profile actually claims, lowercased."""
    names: set[str] = set()
    for exp in profile.get("workExperience") or []:
        name = str((exp or {}).get("company") or "").strip().lower()
        if name:
            names.add(name)
    current = str(profile.get("currentCompany") or "").strip().lower()
    if current:
        names.add(current)
    return names


def _question_names_a_prior_employer(question: str, profile: dict) -> str | None:
    """Return the matching employer when the question asks about a company the
    candidate has genuinely worked for.

    "Have you previously been employed by Amazon or any Amazon subsidiary?" on a
    Twitch posting was being answered "No" for a candidate whose own profile
    lists six years at Amazon. A blanket "No" here is not a conservative
    default — it is a false statement on a real application, and one the
    employer can trivially disprove from its own records.
    """
    q = (question or "").lower()
    if not q:
        return None
    for employer in _prior_employers(profile):
        if employer and employer in q:
            return employer
        for parent, aliases in _EMPLOYER_ALIASES.items():
            if employer in aliases and parent in q:
                return employer
    return None


def _resolve_company_history(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    # Only answer "No" when the question is genuinely about a company the
    # candidate has no history with. See _question_names_a_prior_employer.
    prior = _question_names_a_prior_employer(res.question, profile)
    if prior:
        # "Have you previously applied to..." and conflict-of-interest/relative
        # questions are not employment-history questions, and the profile has no
        # facts for them — leave those unanswered rather than guessing "Yes".
        q_low = (res.question or "").lower()
        if not any(k in q_low for k in ("employ", "work", "intern", "contract", "consult")):
            return
        if "applied" in q_low or "relative" in q_low or "family" in q_low:
            return
        answer = "Yes"
        if opts:
            matched = _match_option(opts, answer)
            res.answer = matched or answer
            res.resolution_method = PROFILE_OPTION_MAPPING if matched else PROFILE_EXACT
        else:
            res.answer = answer
            res.resolution_method = PROFILE_EXACT
        res.profile_key = "workExperience[].company"
        res.source_value = prior
        res.confidence = 1.0
        return

    if opts:
        for o in opts:
            o_low = o.lower()
            if any(neg in o_low for neg in ("never", "no", "not previously", "none of the above", "neither")):
                res.answer = o
                res.resolution_method = DETERMINISTIC_RULE
                res.confidence = 0.95
                return
        res.answer = _match_option(opts, "No") or "No"
    else:
        res.answer = "No"
    res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.95

def _resolve_referral(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Answer referral questions from the absence of any recorded referral.

    CareerOS never records a referrer for an application, so "no referral" is
    the truthful answer rather than a guess — and the free-text variants
    ("please list their name below", "list the company or partner agency
    name(s)") take "N/A" for the same reason. Leaving these blank was staging
    otherwise-complete applications for review over a question with only one
    honest answer.
    """
    referrer = str(profile.get("referredBy") or profile.get("referral") or "").strip()
    if referrer:
        res.answer = referrer
        res.profile_key = "referredBy"
        res.source_value = referrer
        res.resolution_method = PROFILE_EXACT
        res.confidence = 1.0
        return

    if opts:
        matched = _match_option(opts, "No")
        if matched is None:
            for o in opts:
                if o.strip().lower() in ("n/a", "na", "none", "not applicable"):
                    matched = o
                    break
        res.answer = matched or "No"
        res.resolution_method = PROFILE_OPTION_MAPPING if matched else DETERMINISTIC_RULE
    else:
        # Free-text variants ask for a name; "N/A" reads correctly there, while
        # a bare "No" reads oddly in a "please list their name" box.
        q_low = (res.question or "").lower()
        wants_name = any(k in q_low for k in ("list", "name", "who", "company or partner"))
        res.answer = "N/A" if wants_name else "No"
        res.resolution_method = DETERMINISTIC_RULE
    res.profile_key = "referredBy"
    res.source_value = None
    res.confidence = 0.95


def _resolve_school(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    # Prefer the structured education list (which carries the most recent degree
    # first); the flat "school" key remains the fallback inside it.
    _resolve_education_history(res, profile, opts, "school", 0)
    if not res.answer:
        _resolve_from_profile(res, profile, opts, "school")

def _resolve_degree(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_education_history(res, profile, opts, "degree", 0)
    if not res.answer:
        _resolve_from_profile(res, profile, opts, "degree", fallback="Bachelor's Degree")

def _resolve_discipline(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_education_history(res, profile, opts, "discipline", 0)
    if not res.answer:
        _resolve_from_profile(res, profile, opts, "discipline")

def _resolve_education_start_year(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_education_history(res, profile, opts, "start-year", 0)

def _resolve_education_end_year(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_education_history(res, profile, opts, "end-year", 0)

def _resolve_gpa(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Answer a GPA question only from a recorded GPA.

    This used to fall back to "3.5" whenever the profile had no gpa key - and
    the profile has none - so an unanswered GPA question produced an invented
    academic credential at 0.95 confidence, labelled DETERMINISTIC_RULE as
    though it had been derived from something. A made-up GPA on a real
    application is a false statement about the candidate's record, and one an
    employer can check against a transcript. Leave it for the candidate.

    Graduate GPA is preferred when the question asks for it specifically.
    """
    question = (res.question or "").lower()
    wants_graduate = any(
        k in question for k in ("graduate gpa", "grad gpa", "master", "postgraduate", "phd")
    ) and "undergraduate" not in question
    if wants_graduate:
        for key in ("graduateGpa", "gradGpa", "gpaGraduate"):
            if str(profile.get(key) or "").strip():
                _resolve_from_profile(res, profile, opts, key)
                return
    for key in ("undergraduateGpa", "gpa"):
        if str(profile.get(key) or "").strip():
            _resolve_from_profile(res, profile, opts, key)
            return
    # Match how _resolve_citizenship signals "no honest answer available":
    # leave it unanswered so the question reaches the candidate, and say why.
    res.answer = None
    res.confidence = 0.0
    res.resolution_method = UNKNOWN_METHOD
    res.blocking_errors.append(
        "No GPA recorded in the profile; refusing to invent an academic record."
    )

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
    # Match the candidate's CITY as well as their state. Airtable asks "...based
    # in SF Bay Area/NYC ... or 2) based out of Seattle?" — naming the city but
    # never the state, so a state-only check answered "No" for a candidate who
    # genuinely lives in Seattle. That is worse than leaving the field blank: it
    # states something false that can disqualify the application outright.
    has_candidate_state = (
        profile_state in q_low
        or " wa " in q_low
        or "(wa)" in q_low
        or (len(profile_city) > 3 and profile_city in q_low)
    )

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
        yes_opt = _match_option(opts, "Yes")
        if yes_opt:
            res.answer = yes_opt
            res.confidence = 1.0
            res.resolution_method = PROFILE_OPTION_MAPPING
            return
        for opt in opts:
            opt_l = opt.lower()
            if any(s in opt_l for s in ["both", "all of the above", "python", "golang", "go", "ruby", "distributed", "c++", "cpp"]):
                res.answer = opt
                res.confidence = 1.0
                res.resolution_method = PROFILE_OPTION_MAPPING
                return
        res.answer = opts[0]
        res.confidence = 0.9
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = "Yes"
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
    QuestionType.REFERRAL: _resolve_referral,
    QuestionType.SCHOOL: _resolve_school,
    QuestionType.DEGREE: _resolve_degree,
    QuestionType.DISCIPLINE: _resolve_discipline,
    QuestionType.EDUCATION_START_YEAR: _resolve_education_start_year,
    QuestionType.EDUCATION_END_YEAR: _resolve_education_end_year,
    QuestionType.GPA: _resolve_gpa,
    QuestionType.TEST_SCORE: _resolve_test_score,
    QuestionType.LOCATION_CONFIRMATION: _resolve_location_confirmation,
    QuestionType.TECH_STACK_EXPERIENCE: _resolve_tech_stack_experience,
    QuestionType.PREFERRED_LANGUAGE: _resolve_preferred_language,
    QuestionType.TRANSCRIPT: _resolve_transcript,
    QuestionType.LEGAL_AGE: lambda r, p, o: _resolve_legal_age(r, p, o),
}

def _resolve_legal_age(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    if opts:
        res.answer = _match_option(opts, "Yes") or "Yes"
    else:
        res.answer = "Yes"
    res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 1.0

