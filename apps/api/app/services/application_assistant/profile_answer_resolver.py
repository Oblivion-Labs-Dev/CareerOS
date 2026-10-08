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
CANDIDATE_MANIFEST = "CANDIDATE_MANIFEST"
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
    # Non-blocking: the employer's own question may itself be worth a second
    # look (immigration-status screening, a salary-history request some
    # jurisdictions restrict) — see jurisdiction_compliance.py. Distinct from
    # blocking_errors, which is about CareerOS being unable to answer safely;
    # this is about the question being asked at all. Never delays or blocks
    # resolution, and is never legal advice.
    compliance_warnings: list[str] = field(default_factory=list)

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
            "complianceWarnings": self.compliance_warnings,
        }


# ── Helper: get structured work auth ─────────────────────────────────────────

def _get_work_auth(profile: dict[str, Any]) -> dict[str, Any]:
    """Extract the structured workAuth object with safe defaults."""
    wa = profile.get("workAuth") or {}
    return {
        # No default: whether the candidate is legally authorized to work in
        # the US is a factual claim on a real application, and defaulting it
        # to True fabricated that claim for any profile that had not yet
        # recorded it. `_resolve_work_authorized` is the only reader and
        # treats None as "cannot verify" rather than guessing either way.
        "authorizedToWorkInUS": wa.get("authorizedToWorkInUS"),
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


# ── Candidate Answers Manifest ───────────────────────────────────────────────

_MANIFEST_CACHE: list[dict[str, Any]] | None = None


def _find_candidate_manifest_path():
    try:
        from pathlib import Path
        p = Path(__file__).resolve().parents[5] / "data" / "candidate_answers_manifest.json"
        if p.is_file():
            return p
    except Exception:
        pass
    try:
        from pathlib import Path
        for root in [Path.cwd(), Path.cwd().parent]:
            candidate = root / "data" / "candidate_answers_manifest.json"
            if candidate.is_file():
                return candidate
    except Exception:
        pass
    return None


def _load_candidate_manifest() -> list[dict[str, Any]]:
    global _MANIFEST_CACHE
    if _MANIFEST_CACHE is not None:
        return _MANIFEST_CACHE
    manifest_file = _find_candidate_manifest_path()
    if manifest_file and manifest_file.is_file():
        try:
            import json
            with open(manifest_file, "r", encoding="utf-8") as f:
                _MANIFEST_CACHE = json.load(f)
                return _MANIFEST_CACHE
        except Exception:
            pass
    _MANIFEST_CACHE = []
    return _MANIFEST_CACHE


def _normalize_manifest_text(text: str) -> str:
    cleaned = re.sub(r"[\*\:\?\,\.\(\)]", " ", text.lower())
    return " ".join(cleaned.split())


def _map_manifest_value_to_options(answer: str, opts: list[str], topic: str = "") -> str | None:
    if not opts:
        return answer
    matched = _match_option(opts, answer)
    if matched is None and len(opts) == 1:
        matched = opts[0]
    if matched is None and answer.lower() in ("yes", "true", "y"):
        matched = _match_option(opts, "Yes")
    if matched is None and answer.lower() in ("no", "false", "n"):
        matched = _match_option(opts, "No")
    if matched is None:
        matched = _match_yes_no_sentence_option(opts, answer, topic)
    if matched is not None:
        return matched
    if answer.lower() in ("yes", "no", "true", "false", "y", "n"):
        return None
    return answer


_BARE_YES_NO = ("yes", "no", "true", "false", "y", "n")


def _manifest_entry_usable(item: dict[str, Any]) -> bool:
    """Reject entries whose question/answer pairing cannot be right.

    The manifest was captured from live forms, and two capture artefacts made it
    answer real applications wrongly (2026-10-06): checkbox/radio "questions"
    that are really option labels ("Male", "Asian", "I am a current employee" ->
    "Yes"), and answers shifted onto the neighbouring field (essays answered
    "Yes", "Former Employee" answered with a Kubernetes paragraph).
    """
    if item.get("confirmed_by_user") is False:
        return False
    field_type = str(item.get("fieldType") or "").lower()
    if field_type in ("checkbox", "radio"):
        return False
    answer = str(item.get("proposed_answer") or "").strip().lower()
    # A yes/no question can still be captured as a textarea ("Do you have a
    # close personal relationship with...?" -> "No"); only an essay prompt
    # ("Describe...", "Which...") answered yes/no is a shifted answer.
    question = str(item.get("question") or "").strip().lower()
    if (
        field_type == "textarea"
        and answer in _BARE_YES_NO
        and not re.match(r"(do|does|did|are|is|was|were|have|has|had|will|would|can|could)\b", question)
    ):
        return False
    return True


def _match_candidate_manifest_answer(question_text: str, options: list[str] | None = None) -> tuple[str, str] | None:
    manifest = [item for item in _load_candidate_manifest() if _manifest_entry_usable(item)]
    if not manifest:
        return None
    opts = options or []
    norm_q = _normalize_manifest_text(question_text)
    words_q = _significant_words(question_text)

    # 1. Regex match_patterns
    for item in manifest:
        for pat in item.get("match_patterns", []):
            try:
                if re.search(pat, question_text, re.I):
                    val = item.get("proposed_answer")
                    if val is not None and str(val).strip():
                        matched_val = _map_manifest_value_to_options(str(val), opts, str(item.get("question", "")))
                        if matched_val is not None:
                            return str(item.get("id") or "manifest"), matched_val
            except Exception:
                continue

    # 2. Exact normalized text match
    for item in manifest:
        if _normalize_manifest_text(str(item.get("question", ""))) == norm_q:
            val = item.get("proposed_answer")
            if val is not None and str(val).strip():
                matched_val = _map_manifest_value_to_options(str(val), opts, str(item.get("question", "")))
                if matched_val is not None:
                    return str(item.get("id") or "manifest"), matched_val

    # 3. Word overlap (Jaccard >= 0.6)
    best_item = None
    best_score = 0.0
    for item in manifest:
        words_m = _significant_words(str(item.get("question", "")))
        if not words_m or not words_q:
            continue
        overlap = len(words_q & words_m) / max(len(words_q | words_m), 1)
        if overlap > best_score:
            best_score = overlap
            best_item = item

    if best_item and best_score >= 0.6:
        val = best_item.get("proposed_answer")
        # A fuzzy match is a different question. A bare yes/no carried onto a
        # free-text field is how "LinkedIn Profile" got "Yes" instead of a URL.
        if not opts and str(val or "").strip().lower() in _BARE_YES_NO:
            return None
        if val is not None and str(val).strip():
            matched_val = _map_manifest_value_to_options(str(val), opts, str(best_item.get("question", "")))
            if matched_val is not None:
                return str(best_item.get("id") or "manifest"), matched_val

    return None


_PROFILE_IDENTITY_TYPES = frozenset({
    QuestionType.FIRST_NAME, QuestionType.LAST_NAME, QuestionType.FULL_NAME,
    QuestionType.EMAIL, QuestionType.PHONE,
    QuestionType.LINKEDIN, QuestionType.GITHUB, QuestionType.WEBSITE,
})

_REFERRAL_SOURCE_QUESTION = re.compile(r"\b(?:hear|learn)\s+about\b", re.I)
# Most specific first. Each employer names its own careers page ("Career Page",
# "Samsara Careers Site", "Company Website / Careers Page", "BeyondTrust Website").
_CAREERS_PAGE_OPTION_TIERS = (
    re.compile(r"\bcareers?\s*(?:page|site|website)\b", re.I),
    re.compile(r"\bcompany\s+(?:web\s*)?site\b", re.I),
    re.compile(r"\bwebsite\b", re.I),
    # Rvo Health lists its own site as a bare "rvohealth.com".
    re.compile(
        r"^\s*(?:https?://)?(?:www\.)?"
        r"(?!(?:indeed|glassdoor|careerbuilder|linkedin|monster|ziprecruiter|dice|builtin"
        r"|wellfound|angel|handshake|simplyhired|hired|google|facebook|twitter|x|lever"
        r"|greenhouse|ashbyhq|workday|myworkdayjobs|otta|welcometothejungle)\.)"
        r"[a-z0-9-]+\.(?:com|io|co|ai|net|org|health|tech|us)/?\s*$",
        re.I,
    ),
)
_NOT_A_CAREERS_PAGE = re.compile(r"campus|universit|alumni|blog|\bad\b|advert", re.I)


def _careers_page_option(options: list[str]) -> str | None:
    """The one option meaning the employer's own careers page, else None.

    Two candidates at the same tier ("Enova Career Site" / "Pangea Career Site")
    is a real choice, so it is left for the candidate rather than guessed.
    """
    for tier in _CAREERS_PAGE_OPTION_TIERS:
        hits = [o for o in options if tier.search(o) and not _NOT_A_CAREERS_PAGE.search(o)]
        if len(hits) == 1:
            return hits[0]
        if hits:
            return None
    return None


# ── Core resolver ────────────────────────────────────────────────────────────

def _saved_question_mentions(profile: dict[str, Any], screening_id: str, word: str) -> bool:
    for entry in profile.get("screeningAnswers") or []:
        if isinstance(entry, dict) and str(entry.get("id")) == screening_id:
            return word in str(entry.get("question") or "").lower()
    return False


def _match_yes_no_sentence_option(options: list[str], answer: str, topic: str = "") -> str | None:
    """Map a yes/no answer onto sentence-form options.

    Returns None unless exactly one option expresses the wanted polarity, so an
    ambiguous list is left for the caller rather than guessed at. When several
    options share the polarity ("I currently live in this job's location." /
    "I am willing to relocate to this job's location."), the one naming what the
    answered question was about (`topic`) is chosen, and only if it is unique.
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
    if len(wanted) == 1:
        return wanted[0]
    topic_stems = _word_stems(topic)
    if len(wanted) < 2 or not topic_stems:
        return None
    scores = [len(_word_stems(opt) & topic_stems) for opt in wanted]
    best = max(scores)
    return wanted[scores.index(best)] if best and scores.count(best) == 1 else None


def _word_stems(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z]{5,}", (text or "").lower())}


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


_CITIES_AVAILABLE = re.compile(
    r"\b(?:which|what)\s+(?:cities|city|offices?|locations?)\b.{0,40}\b(?:available|able)\s+to\s+work\b", re.I,
)


def _own_city_option(options: list[str], profile: dict[str, Any]) -> str | None:
    """The option naming the candidate's own city ("Seattle", "Seattle, WA",
    "Seattle (Hybrid)"), or None. Any other city would assert a willingness to
    work there that the profile does not record. A suburb's offices are listed
    under the metro ("Seattle" for Auburn), so `metroArea` counts as well."""
    def lead(option: str) -> str:
        return re.split(r"\s*[,(/]\s*|\s+-\s+", option.strip().lower(), maxsplit=1)[0]

    for key in ("city", "metroArea"):
        place = str(profile.get(key) or "").strip().lower()
        if not place:
            continue
        hits = [o for o in options if lead(o) == place]
        if len(hits) == 1:
            return hits[0]
    return None


_FOREIGN_JURISDICTION = re.compile(
    r"\b(?:canada|canadian|europe|european|eu|united\s+kingdom|uk|britain|mexico|ireland|germany"
    r"|france|netherlands|spain|poland|portugal|israel|australia|singapore|japan|brazil|india)\b",
    re.I,
)
# "US" is matched case-sensitively so the pronoun in "tell us" does not count.
_US_ABBREVIATION = re.compile(r"\bU\.S\.(?:A\.)?|\bUSA?\b")
_US_SPELLED_OUT = re.compile(r"\bunited\s+states\b|\bamerica\b", re.I)


def _foreign_jurisdiction_answer(question: str, qtype: QuestionType, profile: dict) -> str | None:
    """Work authorization for a country other than the United States.

    The candidate's authorization is for the United States (and their country
    of citizenship), so "authorized to work in Canada?" is "No" and "require
    sponsorship to work in Canada?" is "Yes". Questions that also name the US
    ("the US or Canada") keep the normal US answer.
    """
    if qtype not in (
        QuestionType.WORK_AUTHORIZED,
        QuestionType.PERMANENT_WORK_AUTHORIZATION,
        QuestionType.SPONSORSHIP_REQUIRED,
    ):
        return None
    text = question or ""
    places = [m.group(0).lower() for m in _FOREIGN_JURISDICTION.finditer(text)]
    places = [p for p in places if not (p == "uk" and not re.search(r"\bUK\b", text))]
    if not places or _US_ABBREVIATION.search(text) or _US_SPELLED_OUT.search(text):
        return None
    citizenship = str(profile.get("citizenshipCountry") or "").strip().lower()
    authorized_there = bool(citizenship) and any(p in citizenship for p in places)
    if qtype == QuestionType.SPONSORSHIP_REQUIRED:
        return "No" if authorized_there else "Yes"
    return "Yes" if authorized_there else "No"


_COMMUTE_FROM_HOME = re.compile(
    r"commut|\breside\b|\bhome\s+address\b|\b(?:currently\s+)?live\s+(?:in|near|within)\b", re.I,
)


def resolve_answer(
    question_text: str,
    profile: dict[str, Any],
    options: list[str] | None = None,
    field_id: str = "",
    answer_lib: list[dict[str, Any]] | None = None,
    question_type: QuestionType | None = None,
) -> AnswerResolution:
    """Resolve an application field answer, then flag the *question itself*
    if it's worth a second look before the candidate answers it.

    The resolution logic lives in `_resolve_answer_impl`, unchanged; this
    wrapper only adds `compliance_warnings` — see `jurisdiction_compliance.py`
    and the field's own docstring on `AnswerResolution`. Kept as a thin outer
    layer rather than folded into the impl so the compliance check runs
    exactly once regardless of which of the impl's many early returns fired.
    """
    resolution = _resolve_answer_impl(
        question_text, profile, options=options, field_id=field_id,
        answer_lib=answer_lib, question_type=question_type,
    )
    from app.services.application_assistant.jurisdiction_compliance import (
        check_immigration_status_screening,
        check_salary_history_request,
    )

    warning = check_immigration_status_screening(question_text) or check_salary_history_request(
        question_text, profile,
    )
    if warning:
        resolution.compliance_warnings.append(warning.message)
        if resolution.validator_status == "UNVALIDATED":
            resolution.validator_status = "WARN"
    return resolution


# A "Please Select" left in the options turns a Yes/No into an unknown list,
# whose fallbacks pick the last option ("No").
_PLACEHOLDER_OPTION = re.compile(
    r"^\s*(?:-+\s*)?(?:please\s+)?(?:select|choose)(?:\s+(?:one|an?\s+option|an?\s+answer))?\s*(?:\.{3}|…)?\s*-*\s*$"
    r"|^\s*-+\s*$|^\s*$",
    re.I,
)


def _resolve_answer_impl(
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
    options = [o for o in options or [] if not _PLACEHOLDER_OPTION.match(o or "")] or None
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

    foreign = _foreign_jurisdiction_answer(question_text, qtype, profile)
    if foreign:
        resolution.answer = (_match_option(opts, foreign) if opts else None) or foreign
        resolution.resolution_method = DETERMINISTIC_RULE
        resolution.profile_key = "workAuth"
        resolution.confidence = 1.0
        return resolution

    visa_type = _visa_type_answer(question_text, profile) if not opts else None
    if visa_type:
        resolution.answer = visa_type
        resolution.resolution_method = PROFILE_EXACT
        resolution.profile_key = "workAuth.authorizationType"
        resolution.confidence = 1.0
        return resolution

    from app.services.application_assistant.answer_classification import match_screening_answer

    screening = match_screening_answer(question_text, profile)
    if screening and qtype in _PROFILE_IDENTITY_TYPES:
        # Cisco's "Email Address" matched a saved "Address 1" answer by its
        # bare "address" wording and was filled with the street address.
        screening = None
    if screening and _education_field(field_id, question_text):
        # One saved "Degree" answer would give every education row the same
        # degree; a row's own entry on the profile answers it.
        screening = None
    if screening and qtype == QuestionType.CITIZENSHIP and not _saved_question_mentions(
        profile, screening[0], "citizen"
    ):
        # A saved work-authorization "Yes" matched "authorized to work" inside a
        # question whose real requirement is citizenship.
        screening = None
    if screening and qtype == QuestionType.SPONSORSHIP_REQUIRED and not _saved_question_mentions(
        profile, screening[0], "sponsor"
    ):
        screening = None
    if screening and qtype == QuestionType.SPONSORSHIP_REQUIRED and sum(
        1 for o in opts if re.match(r"\s*yes\b", o, re.I)
    ) > 1:
        # "Yes, I am on an F1 Visa" / "Yes, I am on an H1B Visa": a saved plain
        # "Yes" cannot say which visa, so the work-auth record picks.
        screening = None
    if screening and qtype == QuestionType.WORK_AUTHORIZED and any(_SPONSOR_WORD.search(o) for o in opts):
        # "Yes, and I will not require sponsorship": a saved plain "Yes" cannot
        # pick between options that also state a sponsorship position.
        screening = None
    if screening and qtype == QuestionType.WORK_AUTHORIZED and re.search(
        r"\bany\s+(?:u\.?s\.?\s+)?employer", question_text, re.I
    ):
        screening = None
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
            if matched is None and "career" in answer.lower() and _REFERRAL_SOURCE_QUESTION.search(question_text):
                matched = _careers_page_option(opts)
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
        if _COMMUTE_FROM_HOME.search(question_text):
            # Akoya: "Select which office is within commuting distance of your
            # home address" asks where the candidate lives, not where they would
            # like to work, so a distant office is a false statement.
            nearby = _own_city_option(opts, profile) or next(
                (o for o in opts if re.search(r"\b(?:do\s+not|don.?t|none)\b", o, re.I)), None
            )
            resolution.answer = nearby
            resolution.resolution_method = PROFILE_EXACT if nearby else UNKNOWN_METHOD
            resolution.confidence = 1.0 if nearby else 0.0
            return resolution
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

    if opts and _CITIES_AVAILABLE.search(question_text):
        own = _own_city_option(opts, profile)
        if own:
            resolution.answer = own
            resolution.resolution_method = PROFILE_EXACT
            resolution.profile_key = "city"
            resolution.confidence = 1.0
        else:
            resolution.resolution_method = UNKNOWN_METHOD
        return resolution

    # Greenhouse's structured employment rows are identified by their element id
    # (company-name-0, start-date-month-1, ...), not by a question type, so they
    # are resolved before the type dispatch below ever sees them. They also
    # precede the answer library: a saved "Degree*" answer cannot tell one
    # school's row from another's.
    employment = _employment_field(field_id, question_text)
    if employment:
        _resolve_employment_history(resolution, profile, opts, employment[0], employment[1])
        resolution.question_type = QuestionType.UNKNOWN.value
        return resolution

    education = _education_field(field_id, question_text)
    if education:
        _resolve_education_history(resolution, profile, opts, education[0], education[1])
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
        _, unproven = _unproven_tech_words(question_text)
        if unproven:
            # Either answer to "N years of Rust?" asserts years of Rust.
            resolution.blocking_errors.append(
                "career.json records no experience with: " + ", ".join(sorted(unproven))
            )
            return resolution
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

    # "Have you been employed by an organization that is a Fiserv client?"
    # reads as a current-employer field and resolved to "Microsoft" - an
    # answer no Yes/No control can take.
    if resolution.answer and _is_yes_no_options(opts) and not _match_option(opts, resolution.answer):
        resolution.answer = None
        resolution.resolution_method = UNKNOWN_METHOD

    # The candidate answers manifest only fills what the profile could not
    # answer: on a factual field the profile wins (owner, 2026-10-06).
    if not resolution.answer:
        manifest_match = _match_candidate_manifest_answer(question_text, opts)
        if manifest_match:
            mid, mval = manifest_match
            resolution.answer = mval
            resolution.resolution_method = CANDIDATE_MANIFEST
            resolution.confidence = 1.0
            resolution.profile_key = f"manifest.{mid}"
            resolution.source_value = mval

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
    if re.search(r"\bextension\b|\bext\b", res.question or "", re.I):
        return
    _resolve_from_profile(res, profile, opts, "phone")

_DIAL_CODE_SUFFIX = re.compile(r"\s*\(\s*\+?(\d{1,4})\s*\)\s*$")


def _resolve_phone_country(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    # "United States of America (+1)" shares its code with two dozen other
    # options (American Samoa, Canada, ...), so the code alone picks whichever
    # comes first; the candidate's country decides among them.
    coded = [(o, _DIAL_CODE_SUFFIX.search(o)) for o in opts]
    if opts and sum(1 for _, m in coded if m) >= max(3, len(opts) // 2):
        code = re.sub(r"\D", "", str(profile.get("phoneCountryCode") or ""))
        country = str(profile.get("country") or "").strip()
        candidates = {
            _DIAL_CODE_SUFFIX.sub("", o).strip(): o
            for o, m in coded
            if m and (not code or m.group(1) == code)
        }
        name = _match_option(list(candidates), country) if country else None
        if name:
            res.answer = candidates[name]
            res.resolution_method = PROFILE_OPTION_MAPPING
            res.profile_key = "country+phoneCountryCode"
            res.source_value = f"{country} {profile.get('phoneCountryCode') or ''}".strip()
            res.confidence = 1.0
            return
    _resolve_from_profile(res, profile, opts, "phoneCountryCode", fallback="United States")


def _resolve_phone_device_type(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "phoneDeviceType")

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
    q = res.question or ""
    if addr_fallback and not opts and re.search(r"\b(?:home|mailing|residential|full|permanent)\s+address\b", q, re.I) \
            and not re.search(r"street|line\s*1", q, re.I):
        # A single "Home address" box wants the whole address, not one line.
        state = str(profile.get("state") or "")
        abbr = next((k for k, v in _STATE_ABBREVIATIONS.items() if v == state.lower()), "")
        state = abbr.upper() or state
        parts = [addr_fallback, str(profile.get("city") or ""), f"{state} {profile.get('zip') or ''}".strip()]
        res.answer = ", ".join(p for p in parts if p)
        res.resolution_method = PROFILE_EXACT
        res.profile_key = "streetAddress+city+state+zip"
        res.confidence = 1.0
        return
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
    """Answer only from a recorded figure.

    This used to default to 8 when nothing was recorded, and again when the
    recorded value would not parse. Years of experience is a checkable fact that
    screening rules gate on, so an invented one is both a false statement and a
    claim that can knock the application out. With nothing recorded the question
    belongs to the candidate — profile_readiness surfaces it as a blocking gap
    so it is asked before a run rather than guessed at during one.
    """
    _, unproven = _unproven_tech_words(res.question or "")
    if unproven:
        res.blocking_errors.append("career.json records no experience with: " + ", ".join(sorted(unproven)))
        return
    raw = profile.get("yearsExperience", profile.get("yearsOfExperience"))
    try:
        yoe_int = int(str(raw).strip())
    except (ValueError, TypeError, AttributeError):
        res.blocking_errors.append(
            "No years-of-experience figure is recorded on the profile, and it "
            "must not be guessed — screening rules gate on this number."
        )
        res.confidence = 0.0
        return

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

_SPONSOR_WORD = re.compile(r"sponsor|\bvisa\b|h-?1b", re.I)
_NO_SPONSOR = re.compile(
    r"\b(?:not|no|never|without|don.?t|won.?t)\b.{0,40}(?:sponsor|visa)|\bno\s+sponsorship", re.I,
)
_DENIES_AUTHORIZATION = re.compile(
    r"\bnot\s+(?:currently\s+|legally\s+)?(?:authori[sz]ed|eligible|allowed|permitted)"
    r"|\bunauthori[sz]ed|\bunknown\b|\bunsure\b|\bdon.?t\s+know\b",
    re.I,
)


def _resolve_work_authorized(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    wa = _get_work_auth(profile)
    auth = wa["authorizedToWorkInUS"]
    if auth is None:
        # Genuinely unknown — decline rather than guess either way. Leaving
        # res.answer unset surfaces this as a real pending question instead
        # of stating a work-authorization status the candidate never gave.
        return
    requires = bool(wa.get("requiresSponsorshipNowOrFuture"))
    if auth and requires and re.search(r"\bany\s+(?:u\.?s\.?\s+)?employer", res.question or "", re.I):
        # An H-1B authorizes work for the sponsoring employer only.
        auth = False
    if opts:
        if auth:
            yes_opts = []
            for opt in opts:
                opt_l = opt.lower()
                if _DENIES_AUTHORIZATION.search(opt):
                    continue
                if opt_l.startswith("yes") or ("authorized" in opt_l and "not" not in opt_l and "unauthorized" not in opt_l) or "visa" in opt_l or "h-1b" in opt_l or "work authorization" in opt_l or "eligible" in opt_l or "source of right" in opt_l:
                    yes_opts.append(opt)
            # "Yes, and I will not require sponsorship" / "Yes, but I will
            # require sponsorship" each also state a sponsorship position.
            states_stance = [o for o in yes_opts if _SPONSOR_WORD.search(o)]
            agreeing = [o for o in states_stance if bool(_NO_SPONSOR.search(o)) != requires]
            if requires and not agreeing:
                # Rvo Health: "I am ONLY allowed to work for my current employer
                # in the U.S. and I will require sponsorship ..." is the H-1B
                # answer, yet reads as neither a "yes" nor "authorized".
                agreeing = [
                    o for o in opts
                    if _SPONSOR_WORD.search(o) and not _NO_SPONSOR.search(o)
                    and not _DENIES_AUTHORIZATION.search(o)
                ]
                states_stance = states_stance + [o for o in agreeing if o not in states_stance]
            neutral = [o for o in yes_opts if o not in states_stance]
            if agreeing or neutral:
                matched = (agreeing or neutral)[0]
            else:
                matched = None if states_stance else _match_option(opts, "Yes")
            res.answer = matched
            if not matched:
                res.resolution_method = UNKNOWN_METHOD
                res.confidence = 0.0
                return
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


_ASKS_VISA_TYPE = re.compile(
    r"what\s+is\s+your\s+(?:current\s+)?(?:work\s+authori[sz]ation|visa|immigration)\s+status"
    r"|(?:list|specify|describe)\s+the\s+type\s+of\s+(?:support|sponsorship|visa)",
    re.I,
)


def _visa_type_answer(question: str, profile: dict) -> str | None:
    """Free text asking which visa the candidate holds or needs is answered with
    the visa itself, not the "Yes" a saved sponsorship answer would give."""
    if not _ASKS_VISA_TYPE.search(question or ""):
        return None
    wa = _get_work_auth(profile)
    visa = str(wa.get("authorizationType") or "").strip()
    return visa if wa.get("requiresSponsorshipNowOrFuture") and visa else None


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
                compact_type = re.sub(r"[-\s]", "", visa_type)
                for opt in opts:
                    if compact_type in re.sub(r"[-\s]", "", opt.lower()):
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
    elif re.search(r"\bwhat\b.{0,20}sponsorship", res.question or "", re.I):
        # Free text asking which sponsorship: "Yes"/"No" doesn't answer it.
        if requires:
            visa_type = str(wa.get("authorizationType") or "").strip()
            if not visa_type:
                res.blocking_errors.append("The profile records no visa type to name")
                return
            res.answer = visa_type
        else:
            res.answer = "None"
        res.resolution_method = PROFILE_EXACT
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
    r"|provide\s+your\s+country"
    r"|what\s+is\s+your\s+(?:citizenship|nationality)\b",
    re.I,
)


def _asks_for_a_country_name(question: str) -> bool:
    return bool(_COUNTRY_VALUED_QUESTION.search(question or ""))


def _resolve_citizenship(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Never claim US citizenship unless profile confirms it."""
    if _asks_for_a_country_name(res.question):
        country = str(profile.get("citizenshipCountry") or "").strip()
        if country and re.search(r"citizen|national", res.question or "", re.I):
            matched = _match_option(opts, country) if opts else country
            if matched:
                res.answer = matched
                res.resolution_method = PROFILE_OPTION_MAPPING if opts else PROFILE_EXACT
                res.profile_key = "citizenshipCountry"
                res.source_value = country
                res.confidence = 1.0
                return
        # Leave unanswered: a yes/no answer forced into a country list
        # produces a fabricated country.
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
    # Some boards put the export-control question the other way round and ask
    # for a country rather than a status: "In which country did you obtain
    # citizenship, nationality, or permanent residency?" Answering that with
    # "None of the above" is a non-answer, so the field stayed empty - the same
    # status-versus-value confusion as the time-zone question.
    question = (res.question or "").lower()
    if re.search(r"(which|what)\s+countr(y|ies)", question):
        country = str(
            profile.get("citizenshipCountry") or profile.get("citizenship") or ""
        ).strip()
        if not country:
            res.blocking_errors.append(
                "This asks which country the candidate holds citizenship in, and "
                "no citizenship country is recorded on the profile."
            )
            res.confidence = 0.0
            return
        if opts:
            matched = _match_option(opts, country)
            if not matched:
                res.blocking_errors.append(
                    f"Citizenship country is {country!r}, but none of the offered "
                    "options match it."
                )
                res.confidence = 0.0
                return
            res.answer = matched
            res.resolution_method = PROFILE_OPTION_MAPPING
        else:
            res.answer = country
            res.resolution_method = PROFILE_EXACT
        res.profile_key = "citizenshipCountry"
        res.source_value = country
        res.confidence = 0.95
        return

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


_NO_CLEARANCE = re.compile(
    r"^\s*no\b|\bnone\b|\bno\s+(?:active\s+|us\s+|u\.s\.\s+)?(?:security\s+)?clearance|"
    r"\b(?:do|does)\s+not\s+(?:have|hold)\b|\bnever\s+held\b|\bnot\s+applicable\b|^\s*n/?a\s*$",
    re.I,
)
_CLAIMS_CLEARANCE = re.compile(r"^\s*yes\b|\bi\s+(?:currently\s+)?(?:hold|held|have\s+held)\s+a\b", re.I)


def _no_clearance_option(opts: list[str]) -> str | None:
    safe = [o for o in opts if _NO_CLEARANCE.search(o) and not _CLAIMS_CLEARANCE.search(o)]
    return safe[0] if safe else None


def _resolve_clearance_level(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    sec = _get_security(profile)
    if sec["hasHeldUSSecurityClearance"]:
        answer = profile.get("clearanceLevel", "Secret")
    else:
        answer = "None"
    if opts and not sec["hasHeldUSSecurityClearance"]:
        # Muon Space: a substring "no" matched inside "not listed here" and sent
        # "Yes, but I currently hold a US Security Clearance not listed here".
        safe = _no_clearance_option(opts)
        if safe is None:
            res.blocking_errors.append("No offered option states that the candidate holds no clearance.")
            res.confidence = 0.0
            return
        res.answer = safe
        res.resolution_method = PROFILE_OPTION_MAPPING
        res.confidence = 1.0
        res.profile_key = "security.hasHeldUSSecurityClearance"
        res.source_value = sec["hasHeldUSSecurityClearance"]
        return
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


_SOUTH_ASIAN_ANCESTRIES = {"indian", "pakistani", "bangladeshi", "sri lankan", "nepali", "bhutanese", "maldivian"}


def _resolve_race(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Q: What is your race? → Asian.

    SAFETY: Filter out ethnicity options — they can NEVER be answers to a race question.
    """
    val = profile.get("raceEthnicity") or APPLICATION_FIELD_DEFAULTS.get("raceEthnicity", "Prefer not to answer")

    if opts:
        # SAFETY: Remove ethnicity options from race question. Combined EEOC
        # lists qualify each race "(Not Hispanic or Latino)"; those stay.
        safe_opts = [o for o in opts if not _is_ethnicity_option(o) or _is_race_option(o)]
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
        # When the form offers the candidate's own, more specific ancestry, that
        # is the truthful answer and is preferred over the broad category. The
        # candidate is South Asian and confirmed both are correct — "which one
        # depends on the granularity the form asks for". Keyed on an explicitly
        # recorded sub-category, never inferred, so this cannot become the
        # guess-a-narrower-option failure the comment above describes.
        specific = str(profile.get("raceEthnicitySpecific") or "").strip()
        if specific:
            specific_word = re.compile(rf"\b{re.escape(specific)}\b", re.I)
            # "Indian" must never select "American Indian or Alaska Native".
            exact = [
                o for o in safe_opts
                if specific_word.search(o) and not re.search(r"american\s+indian|alaska|native\s+american", o, re.I)
            ]
            if not exact and specific.lower() in _SOUTH_ASIAN_ANCESTRIES:
                exact = [o for o in safe_opts if re.search(r"\bsouth\s+asian", o, re.I)]
            if len(exact) == 1:
                res.answer = exact[0]
                res.resolution_method = PROFILE_OPTION_MAPPING
                res.profile_key = "raceEthnicitySpecific"
                res.source_value = specific
                res.confidence = 0.95
                return

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
    lgbtq = str(profile.get("lgbtq") or "").strip()
    if lgbtq and re.search(r"lgbt|queer", res.question or "", re.I):
        # "Do you identify as a member of the LGBTQ+ community?" is a yes/no.
        matched = _match_option(opts, lgbtq) if opts else lgbtq
        if matched:
            res.answer = matched
            res.resolution_method = PROFILE_OPTION_MAPPING if opts else PROFILE_EXACT
            res.profile_key = "lgbtq"
            res.source_value = lgbtq
            res.confidence = 1.0
            return
    if val:
        answer = str(val)
    else:
        answer = "Decline"
    if opts:
        # "Heterosexual / Straight": forms use either word.
        synonyms = [s for s in re.split(r"\s*/\s*|\s*,\s*", answer) if s]
        matched = next((m for m in (_match_option(opts, s) for s in [answer, *synonyms]) if m), None) \
            or _find_decline_option(opts)
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
        if negative is None and not _claims_service(profile):
            # Fiserv: "No, or I prefer not to identify" names neither veteran nor military.
            plain_no = [o for o in opts if re.match(r"\s*no\b", o, re.I)]
            negative = plain_no[0] if len(plain_no) == 1 else None
        if negative:
            res.answer = negative


def _claims_service(profile: dict) -> bool:
    veteran = str(profile.get("veteran") or "").lower()
    return bool(veteran) and not re.search(r"\bnot\b|\bno\b|\bnever\b|\bnon\b", veteran)

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

_CLAIMS_A_CONTACT = re.compile(
    r"recruit|referr|employee|contacted|reached\s+out|inmail|message|customer|partner|friend|family|"
    r"colleague|coworker|alumni|\bi\s+use\b|\bi\s+am\s+an?\b|\bi'?m\s+an?\b",
    re.I,
)


def _resolve_how_heard(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """BUG FIX: Was selecting random options. Now uses profile.jobDiscoveryDefault."""
    if re.search(r"\binfluence\b|\brate\b|how\s+much", res.question or "", re.I):
        # DoorDash: "How much did content from the Engineering blog influence
        # your decision?" is the candidate's opinion, not a discovery channel.
        res.resolution_method = UNKNOWN_METHOD
        res.confidence = 0.0
        return
    # No channel on file means no answer: a built-in "LinkedIn" default once
    # told Upstart "A recruiter contacted me (LinkedIn message)".
    default = str(profile.get("jobDiscoveryDefault") or "").strip()
    if not default:
        res.resolution_method = UNKNOWN_METHOD
        res.confidence = 0.0
        return
    if opts:
        # Options asserting a contact or connection are claims the channel
        # alone cannot support, so they are never matched.
        neutral = [o for o in opts if not _CLAIMS_A_CONTACT.search(o)]
        matched = _careers_page_option(neutral) if "career" in default.lower() else None
        matched = (matched
                   or _match_option(neutral, default)
                   or next((o for o in neutral if o.strip().lower() == "other"), None))
        if not matched:
            res.resolution_method = UNKNOWN_METHOD
            res.confidence = 0.0
            return
        res.answer = matched
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

    "Have you used X?" (Robinhood) / "Are you familiar with X?" (Twitch) are
    personal facts the profile does not record, so they are left for the
    candidate unless a saved screening answer covers them.
    """
    q_low = (res.question or "").lower()
    is_product_use = bool(re.search(r"have\s+you\s+used\b|are\s+you\s+familiar\s+with", q_low))
    if is_product_use:
        res.resolution_method = UNKNOWN_METHOD
        res.confidence = 0.0
        res.blocking_errors.append("Whether the candidate uses this product is not recorded in the profile.")
        return
    is_event_meet = bool(re.search(r"meet\s+with\s+or\s+see|attending\s+an?\s+event|conference", q_low))
    if is_event_meet:
        if opts:
            res.answer = _match_option(opts, "No") or "No"
            res.resolution_method = PROFILE_OPTION_MAPPING
        else:
            res.answer = "No"
            res.resolution_method = DETERMINISTIC_RULE
        res.confidence = 0.95
        return
    default = "I learned about the company through this job posting"
    if opts:
        posting_opt = next((o for o in opts if re.search(r"job\s*posting|recruiter", o, re.IGNORECASE)), None)
        heard_opt = next((o for o in opts if re.search(r"heard.*didn.?t\s*know", o, re.IGNORECASE)), None)
        res.answer = posting_opt or heard_opt
        res.resolution_method = DETERMINISTIC_RULE if res.answer else UNKNOWN_METHOD
        if not res.answer:
            res.confidence = 0.0
            return
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
    requires_relocation_assistance = bool(re.search(r"\b(?:require|need)\b.{0,15}relocat", q_low))
    if requires_relocation_assistance:
        # Not asking the company to pay for a move commits the candidate to
        # nothing, so "No" stays a safe default here.
        _resolve_from_profile(res, profile, opts, "relocateAssistance", fallback="No")
        return
    local = _local_to_named_place(res.question or "", profile)
    if local:
        matched = _match_option(opts, local) if opts else local
        if matched:
            res.answer = matched
            res.resolution_method = PROFILE_EXACT
            res.profile_key = "city+state"
            res.confidence = 1.0
        return
    lives_here = _lives_here_option(opts) if _job_is_in_candidate_city(profile) else None
    if lives_here:
        res.answer = lives_here
        res.resolution_method = PROFILE_OPTION_MAPPING
        res.profile_key = "city+jobLocation"
        res.source_value = profile.get("_jobLocation")
        res.confidence = 1.0
        return
    if re.search(r"\bplans?\s+to\s+relocate\s+within\b", q_low):
        # Concrete plans, not willingness: only the candidate knows.
        return
    if opts and str(profile.get("relocate") or "").strip().lower() in ("yes", "true"):
        # Brex offers "Yes, I'm currently located here" before "Yes, I'd
        # relocate"; willingness to move is the second, not the first yes.
        moving = [
            o for o in opts
            if re.search(r"relocat|\bmove\b", o, re.I) and not re.search(r"\bnot\b|^\s*no\b|n['’]t\b", o, re.I)
        ]
        if len(moving) == 1:
            res.answer = moving[0]
            res.resolution_method = PROFILE_OPTION_MAPPING
            res.profile_key = "relocate"
            res.confidence = 1.0
            return
    # Willingness to move is a promise on a real application, so it comes from
    # the profile or not at all — never a hardcoded "Yes".
    _resolve_from_profile(res, profile, opts, "relocate")


_LOCAL_TO = re.compile(
    r"^\s*are\s+you\s+(?:currently\s+)?(?:local\s+to|located\s+in|based\s+in|living\s+in)\s+(?:the\s+)?([^?*]+)", re.I
)


def _local_to_named_place(question: str, profile: dict) -> str | None:
    """"Are you local to Ann Arbor, MI?" is a fact about where the candidate
    lives: Yes when it names their city, No when it names a different state.
    A region without a state ("the Puget Sound area") or any either/or
    phrasing is left unanswered."""
    m = _LOCAL_TO.match(question)
    if not m or re.search(r"\bor\b|willing|relocat|commut", question, re.I):
        return None
    place = m.group(1).strip().lower()
    city = str(profile.get("city") or "").split(",")[0].strip().lower()
    state = str(profile.get("state") or "").strip().lower()
    state_abbrev = next((a for a, n in _STATE_ABBREVIATIONS.items() if n == state), state if len(state) == 2 else "")
    if city and re.search(rf"\b{re.escape(city)}\b", place):
        return "Yes"
    abbrev = re.search(r",\s*([a-z]{2})\s*$", place)
    named_state = abbrev.group(1) if abbrev else next(
        (a for a, n in _STATE_ABBREVIATIONS.items() if re.search(rf"\b{n}\b", place)), "")
    if named_state and state_abbrev and named_state != state_abbrev:
        return "No"
    return None


_LIVES_HERE = re.compile(
    r"(?:live|located|reside)\s+(?:here|nearby|in\s+(?:this|the))|currently\s+(?:live|located|reside)", re.I
)


def _job_is_in_candidate_city(profile: dict) -> bool:
    """`_jobLocation` is set by the executor from the posting being applied to."""
    job_location = str(profile.get("_jobLocation") or "").lower()
    city = str(profile.get("city") or "").split(",")[0].strip().lower()
    return bool(job_location and len(city) > 2 and city in job_location)


def _lives_here_option(opts: list[str]) -> str | None:
    matches = [
        o for o in opts
        if _LIVES_HERE.search(o) and not re.search(r"\bnot\b|^\s*no\b|n['’]t\b", o, re.I)
    ]
    return matches[0] if len(matches) == 1 else None

# Wording that turns a work-arrangement question into a commitment about being
# in a particular place, rather than a preference between schedules.
_PLACE_COMMITMENT_PATTERNS = (
    r"relocat",
    r"\bcommut",
    r"come\s+(?:in\s+)?on-?site",
    r"\bhq\b\s+(?:is\s+)?in\b",
    r"headquarter",
    r"based\s+(?:out\s+)?in\b",
    r"office\s+(?:is\s+)?(?:located\s+)?in\b",
    r"in-?\s?office\s+in\b",
    r"willing\s+to\s+(?:move|relocate)",
)


_PRESENCE_CLAIM = re.compile(
    r"located\s+(?:here|nearby|near|in)|live\s+(?:here|nearby|near|in)|\blocal\b|\bnearby\b|relocat",
    re.I,
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


_PRESENT_LOCATION_QUESTION = re.compile(
    r"\b(?:are\s+you|do\s+you)\s+(?:currently\s+)?(?:located|live|living|reside|residing|based)\b", re.I
)
_RELOCATION_ALTERNATIVE = re.compile(r"\bor\b[^?]*\b(?:willing|open|able)\b|relocat", re.I)


def _present_location_answer(question: str, profile: dict) -> str | None:
    """"Are you located within commuting distance of Colorado Springs, CO and
    willing to be hybrid?" asks where the candidate lives now. Willingness to
    relocate does not make that true, so it is "No" when every place named is in
    another state. Left unanswered when it names the candidate's own state (they
    may well be in range), names no state, or offers relocation as an option."""
    if not _PRESENT_LOCATION_QUESTION.search(question) or _RELOCATION_ALTERNATIVE.search(question):
        return None
    text = question.lower()
    state = str(profile.get("state") or "").strip().lower()
    abbrev = next((a for a, n in _STATE_ABBREVIATIONS.items() if n == state), state if len(state) == 2 else "")
    if (state and re.search(rf"\b{re.escape(state)}\b", text)) or (
        abbrev and re.search(rf",\s*{abbrev.upper()}\b", question)
    ):
        return None
    # Abbreviations count only in capitals: ", or Mexico" is not Oregon.
    named = [a.lower() for a in re.findall(r",\s*([A-Z]{2})\b", question) if a.lower() in _STATE_ABBREVIATIONS]
    named += [a for a, n in _STATE_ABBREVIATIONS.items() if re.search(rf"\b{n}\b", text)]
    return "No" if named else None


def _resolve_work_arrangement(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Hybrid / remote / onsite schedule questions — the candidate is open to any."""
    if _asks_to_commit_to_a_place(res.question, profile):
        present = _present_location_answer(res.question, profile)
        if present is not None:
            res.answer = (_match_option(opts, present) if opts else present) or None
            res.resolution_method = PROFILE_EXACT if res.answer else UNKNOWN_METHOD
            res.profile_key = "state"
            res.confidence = 1.0 if res.answer else 0.0
            return
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
        asks_preference = bool(stored) and bool(re.search(r"\bprefer", res.question or "", re.I))
        res.answer = stored if asks_preference else "Yes"
        res.resolution_method = PROFILE_EXACT if asks_preference else DETERMINISTIC_RULE
        res.confidence = 0.9 if asks_preference else 0.7
        return

    if stored and re.search(r"\bprefer", res.question or "", re.I):
        # "What is your preferred work arrangement?" asks for the preference
        # (Remote), not the willingness to do any of them.
        matched = _match_option(opts, stored)
        if matched:
            res.answer = matched
            res.resolution_method = PROFILE_OPTION_MAPPING
            res.profile_key = "workArrangement"
            res.confidence = 1.0
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
    if matched_yes and _PRESENCE_CLAIM.search(matched_yes):
        # Brex: "Yes, I'm currently located here" is the first yes-option, but
        # the resolver never sees the job's location, so it cannot say that.
        _resolve_relocate(res, profile, opts)
        if not res.answer:
            res.resolution_method = UNKNOWN_METHOD
        return
    if matched_yes:
        res.answer = matched_yes
        res.resolution_method = DETERMINISTIC_RULE
        res.confidence = 0.9
        return

    # A genuine single-choice among Remote/Hybrid/Onsite with no umbrella
    # option isn't answerable from "open to all" alone — leave it for review
    # rather than guessing which one this specific listing wants to hear.

# Standard and daylight-saving offsets.
_TIMEZONE_UTC_OFFSETS: dict[str, tuple[int, int]] = {
    "America/Los_Angeles": (-8, -7),
    "America/Denver": (-7, -6),
    "America/Phoenix": (-7, -7),
    "America/Chicago": (-6, -5),
    "America/New_York": (-5, -4),
}


def _resolve_timezone_availability(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """"Are you ok working Eastern/Central Time?"-style questions — the
    candidate is generally flexible on core-hours overlap, same spirit as
    being open to any work arrangement.

    "Do you live in UTC -6 through UTC+2?" is a fact about where the candidate
    lives, so it is checked against the profile's time zone instead.
    """
    answer = "Yes"
    offsets = [
        int(sign.replace("\u2212", "-") + hours)
        for sign, hours in re.findall(r"(?:UTC|GMT)\s*([+\-\u2212])\s*(\d{1,2})", res.question or "", re.I)
    ]
    if len(offsets) == 2 and re.search(r"\b(?:live|located|based|reside)\b", res.question or "", re.I):
        own = _TIMEZONE_UTC_OFFSETS.get(str(profile.get("timezone") or ""))
        if own is None:
            res.blocking_errors.append("The profile records no time zone to compare with the asked UTC range.")
            res.resolution_method = UNKNOWN_METHOD
            res.confidence = 0.0
            return
        low, high = min(offsets), max(offsets)
        answer = "Yes" if all(low <= o <= high for o in own) else "No"
        res.profile_key = "timezone"
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
    # No `fallback=` here: "Open / Negotiable" is a real, specific claim about
    # the candidate's negotiating stance, not a universally-true non-answer
    # like RACE's "Prefer not to answer". Submitting it when the candidate
    # never actually said that is exactly the guess this module's other
    # resolvers are written to refuse. Leaving it unresolved surfaces as a
    # pending question the candidate answers once, same as any other blocked
    # field — not a fabricated answer on a live application.
    _resolve_from_profile(res, profile, opts, "salaryExpectations")

def _only_option(opts: list[str]) -> str | None:
    """A single-option control (an acknowledgement) has one honest answer; with
    several, picking the first is a guess."""
    return opts[0] if len(opts) == 1 else None


def _resolve_notice_period(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    q_low = (res.question or "").lower()
    if any(k in q_low for k in ("job search", "active are you", "search activity", "search status")):
        if opts:
            matched = (_match_option(opts, "Actively looking")
                       or _match_option(opts, "Open to opportunities")
                       or _match_option(opts, "Ready to interview")
                       or _match_option(opts, "Active"))
            res.answer = matched or _only_option(opts)
            res.resolution_method = PROFILE_OPTION_MAPPING if res.answer else UNKNOWN_METHOD
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
        res.answer = matched or _only_option(opts)
        res.resolution_method = PROFILE_OPTION_MAPPING if res.answer else UNKNOWN_METHOD
    else:
        res.answer = str(val)
        res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.95


def _resolve_sms_consent(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "smsConsent",
                          fallback=APPLICATION_FIELD_DEFAULTS.get("smsConsent", "No"))

def _resolve_marketing_consent(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_from_profile(res, profile, opts, "marketingConsent",
                          fallback=APPLICATION_FIELD_DEFAULTS.get("marketingConsent", "No"))

#: Descriptive level -> the CEFR band a form offering bare codes expects.
_CEFR_FOR_LEVEL = {
    "native": "C2", "bilingual": "C2", "fluent": "C2",
    "proficient": "C2", "professional": "C1", "advanced": "C1",
    "intermediate": "B2", "conversational": "B1", "basic": "A2",
}


def _resolve_english_proficiency(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Answer from the level the candidate recorded, not from a constant.

    This used to assert "Fluent" unconditionally, reading nothing from the
    profile. That is a claim about the candidate made on their behalf, and it
    was wrong here — the recorded level is "Proficient". A self-assessment
    belongs to the person being assessed, so with nothing recorded this now goes
    to review rather than picking a level.
    """
    target = str(
        profile.get("englishLevel")
        or profile.get("english_level")
        or profile.get("englishProficiency")
        or ""
    ).strip()

    if not target:
        res.blocking_errors.append(
            "No English proficiency level is recorded on the profile. Set one on "
            "the Profile page (Citizenship & work eligibility) rather than having "
            "a level asserted on your behalf."
        )
        res.confidence = 0.0
        return

    # Pleased: "Do you have English proficiency?" is a Yes/No, sometimes on a
    # custom dropdown whose options are not read, so the phrasing decides it too.
    # Fluency says nothing about whether English is the candidate's first language.
    asks_native = re.search(r"native|first\s+language|mother\s+tongue", res.question or "", re.I)
    yes_no_opts = bool(opts) and {o.strip().lower() for o in opts} <= {"yes", "no"}
    yes_no_phrasing = not opts and re.match(r"\s*(do|are|is|can|have)\b", res.question or "", re.I)
    if (yes_no_opts or yes_no_phrasing) and not asks_native:
        if _CEFR_FOR_LEVEL.get(target.lower()) not in ("C1", "C2"):
            res.blocking_errors.append(
                f"The recorded English level is {target!r}; whether that counts as "
                "proficient is the candidate's call."
            )
            res.confidence = 0.0
            return
        res.answer = _match_option(opts, "Yes") if opts else "Yes"
        res.resolution_method = PROFILE_OPTION_MAPPING if opts else DETERMINISTIC_RULE
    elif opts:
        # Some forms (observed on Sezzle) offer bare CEFR codes (A1-C2)
        # instead of descriptive text — "Fluent"/"Professional"/"Native"
        # share no substring with "C2", so a descriptive-text match always
        # missed and left the field unresolved.
        cefr_opts = {o.strip().upper() for o in opts}
        if cefr_opts & {"A1", "A2", "B1", "B2", "C1", "C2"}:
            band = _CEFR_FOR_LEVEL.get(target.lower(), "C1")
            matched = _match_option(opts, band) or _match_option(opts, "C1")
        else:
            matched = (
                _match_option(opts, target)
                or _match_option(opts, "Fluent")
                or _match_option(opts, "Professional")
                or _match_option(opts, "Native")
            )
        if not matched:
            res.blocking_errors.append(
                f"The recorded English level is {target!r}, but none of the offered "
                "options express it."
            )
            res.confidence = 0.0
            return
        res.answer = matched
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = target
        res.resolution_method = PROFILE_EXACT

    res.profile_key = "englishLevel"
    res.source_value = target
    res.confidence = 0.95

#: US state / territory -> IANA zone and the name application forms expect.
#: Only the unambiguous ones. A state split across zones is deliberately absent
#: so it falls through to review rather than guessing the wrong half.
_STATE_TIMEZONES: dict[str, tuple[str, str]] = {
    "washington": ("America/Los_Angeles", "Pacific Time (PT)"),
    "oregon": ("America/Los_Angeles", "Pacific Time (PT)"),
    "california": ("America/Los_Angeles", "Pacific Time (PT)"),
    "nevada": ("America/Los_Angeles", "Pacific Time (PT)"),
    "utah": ("America/Denver", "Mountain Time (MT)"),
    "colorado": ("America/Denver", "Mountain Time (MT)"),
    "new mexico": ("America/Denver", "Mountain Time (MT)"),
    "montana": ("America/Denver", "Mountain Time (MT)"),
    "wyoming": ("America/Denver", "Mountain Time (MT)"),
    "arizona": ("America/Phoenix", "Mountain Time (MT, no DST)"),
    "illinois": ("America/Chicago", "Central Time (CT)"),
    "texas": ("America/Chicago", "Central Time (CT)"),
    "minnesota": ("America/Chicago", "Central Time (CT)"),
    "wisconsin": ("America/Chicago", "Central Time (CT)"),
    "iowa": ("America/Chicago", "Central Time (CT)"),
    "missouri": ("America/Chicago", "Central Time (CT)"),
    "arkansas": ("America/Chicago", "Central Time (CT)"),
    "louisiana": ("America/Chicago", "Central Time (CT)"),
    "oklahoma": ("America/Chicago", "Central Time (CT)"),
    "alabama": ("America/Chicago", "Central Time (CT)"),
    "mississippi": ("America/Chicago", "Central Time (CT)"),
    "new york": ("America/New_York", "Eastern Time (ET)"),
    "new jersey": ("America/New_York", "Eastern Time (ET)"),
    "massachusetts": ("America/New_York", "Eastern Time (ET)"),
    "pennsylvania": ("America/New_York", "Eastern Time (ET)"),
    "virginia": ("America/New_York", "Eastern Time (ET)"),
    "maryland": ("America/New_York", "Eastern Time (ET)"),
    "georgia": ("America/New_York", "Eastern Time (ET)"),
    "north carolina": ("America/New_York", "Eastern Time (ET)"),
    "south carolina": ("America/New_York", "Eastern Time (ET)"),
    "ohio": ("America/New_York", "Eastern Time (ET)"),
    "connecticut": ("America/New_York", "Eastern Time (ET)"),
    "maine": ("America/New_York", "Eastern Time (ET)"),
    "vermont": ("America/New_York", "Eastern Time (ET)"),
    "new hampshire": ("America/New_York", "Eastern Time (ET)"),
    "rhode island": ("America/New_York", "Eastern Time (ET)"),
    "delaware": ("America/New_York", "Eastern Time (ET)"),
    "west virginia": ("America/New_York", "Eastern Time (ET)"),
}

_STATE_ABBREVIATIONS = {
    "wa": "washington", "or": "oregon", "ca": "california", "nv": "nevada",
    "ut": "utah", "co": "colorado", "nm": "new mexico", "mt": "montana",
    "wy": "wyoming", "az": "arizona", "il": "illinois", "tx": "texas",
    "mn": "minnesota", "wi": "wisconsin", "ia": "iowa", "mo": "missouri",
    "ar": "arkansas", "la": "louisiana", "ok": "oklahoma", "al": "alabama",
    "ms": "mississippi", "ny": "new york", "nj": "new jersey",
    "ma": "massachusetts", "pa": "pennsylvania", "va": "virginia",
    "md": "maryland", "ga": "georgia", "nc": "north carolina",
    "sc": "south carolina", "oh": "ohio", "ct": "connecticut", "me": "maine",
    "vt": "vermont", "nh": "new hampshire", "ri": "rhode island",
    "de": "delaware", "wv": "west virginia",
}


def candidate_timezone(profile: dict) -> tuple[str, str] | None:
    """The candidate's own time zone, as (IANA id, display name).

    Prefers an explicit profile value, then derives one from the recorded
    state. Returns ``None`` rather than a guess when the location does not
    resolve unambiguously - an invented time zone on a submitted application is
    a false statement, and review is the correct outcome.
    """
    explicit = str(profile.get("timezone") or profile.get("timeZone") or "").strip()
    if explicit:
        return (explicit, explicit)

    haystacks = [
        str(profile.get("state") or ""),
        str(profile.get("location") or ""),
        str(profile.get("currentLocation") or ""),
    ]
    for raw in haystacks:
        low = raw.strip().lower()
        if not low:
            continue
        if low in _STATE_TIMEZONES:
            return _STATE_TIMEZONES[low]
        for part in re.split(r"[,/|]", low):
            token = part.strip()
            if token in _STATE_TIMEZONES:
                return _STATE_TIMEZONES[token]
            expanded = _STATE_ABBREVIATIONS.get(token)
            if expanded:
                return _STATE_TIMEZONES[expanded]
    return None


def _resolve_timezone_location(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """"What time zone are you in?" - wants a zone, not a yes/no.

    TIMEZONE_AVAILABILITY answers "Yes", which is right for "can you work
    Eastern hours?" and meaningless here; the field stayed empty and the
    application was held for a DOM verification mismatch.
    """
    resolved = candidate_timezone(profile)
    if not resolved:
        res.blocking_errors.append(
            "The profile does not record a time zone and none could be derived "
            "from the recorded location, so this needs a human answer."
        )
        res.confidence = 0.0
        return

    iana, display = resolved
    if opts:
        matched = (
            _match_option(opts, display)
            or _match_option(opts, iana)
            or _match_option(opts, display.split(" (")[0])
        )
        if not matched:
            res.blocking_errors.append(
                f"The candidate is in {display}, but none of the offered options "
                "match it; picking the nearest would state the wrong zone."
            )
            res.confidence = 0.0
            return
        res.answer = matched
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = display
        res.resolution_method = DETERMINISTIC_RULE

    res.profile_key = "location"
    res.source_value = profile.get("location")
    res.confidence = 0.92


def _resolve_employer_count(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """"How many companies have you worked for?" - counted from work history.

    Previously intercepted by DEGREE, because the question dates its window by
    naming a degree, so an employer count was answered with a qualification
    level.
    """
    history = profile.get("workExperience") or profile.get("experience") or []
    employers = {
        str(entry.get("company") or entry.get("employer") or "").strip().lower()
        for entry in history
        if isinstance(entry, dict)
    }
    employers.discard("")

    if not employers:
        res.blocking_errors.append(
            "No work history is recorded on the profile, so the number of "
            "employers cannot be counted without inventing it."
        )
        res.confidence = 0.0
        return

    count = str(len(employers))
    if opts:
        matched = _match_option(opts, count)
        if not matched:
            res.blocking_errors.append(
                f"The profile records {count} employers, but none of the offered "
                "options express that."
            )
            res.confidence = 0.0
            return
        res.answer = matched
        res.resolution_method = PROFILE_OPTION_MAPPING
    else:
        res.answer = count
        res.resolution_method = PROFILE_EXACT

    res.profile_key = "workExperience"
    res.source_value = sorted(employers)
    res.confidence = 0.9


def _resolve_employment_gap(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Resolve employment/work history gap disclosures deterministically.

    When asked to explain gaps in employment history (e.g. 'Please explain any
    gaps in your work history. If none, please say N/A.'), answer 'N/A' (or select
    'N/A' / 'None' / 'No' if options exist).
    """
    if opts:
        for candidate in ["N/A", "None", "No", "No gaps"]:
            matched = _match_option(opts, candidate)
            if matched:
                res.answer = matched
                res.resolution_method = PROFILE_OPTION_MAPPING
                res.confidence = 1.0
                return
        res.resolution_method = UNKNOWN_METHOD
        res.confidence = 0.0
    else:
        res.answer = "N/A"
        res.resolution_method = DETERMINISTIC_RULE
        res.confidence = 1.0


def _resolve_originality_declaration(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    """Affirmed, at the candidate's explicit instruction.

    The declaration reads, in Canonical's wording: "I agree to use only my own
    words. I understand that plagiarism, the use of AI or other generated
    content will disqualify my application."

    This resolver originally refused to answer, on the grounds that CareerOS
    drafts with a language model and ticking the box would therefore assert
    something untrue. The candidate was shown that reasoning in full and
    overruled it, which is their call to make: they are the one making the
    declaration, and they are the one who bears it if an employer disagrees.

    The instruction came with a condition attached — that answers "need to
    sound more human" — and the substance of the position is that the answers
    are composed from the candidate's own recorded stories and reviewed by
    them, so the words are theirs in the sense the clause is asking about.
    That is a defensible reading; it is simply not one automation may adopt on
    someone's behalf without being asked.

    Recorded here rather than argued again, so a future reader knows this is a
    deliberate decision and not an oversight.
    """
    target = "I agree"
    if opts:
        res.answer = (
            _match_option(opts, "I agree")
            or _match_option(opts, "Agree")
            or _match_option(opts, "Yes")
            or _match_option(opts, "I acknowledge")
            or _match_option(opts, "Accept")
            or _only_option(opts)
        )
    else:
        res.answer = target
    res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.9


def _resolve_privacy_consent(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    target = "I agree"
    if opts:
        res.answer = _match_option(opts, "I agree") or _match_option(opts, "Agree") or _match_option(opts, "Yes") or _match_option(opts, "I acknowledge") or _match_option(opts, "Accept") or _only_option(opts)
    else:
        res.answer = target
    res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 0.95

def _resolve_accuracy_confirmation(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    if opts:
        res.answer = (
            _match_option(opts, "Yes")
            or _match_option(opts, "I acknowledge")
            or _match_option(opts, "Acknowledge")
            or _match_option(opts, "Agree")
            or "Yes"
        )
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

    matched = _match_option(opts, value) if opts else None
    if matched is None and kind == "degree" and opts:
        matched = _option_at_degree_level(opts, value)
    if matched is not None:
        res.answer = matched
        res.resolution_method = PROFILE_OPTION_MAPPING
    elif not opts or kind == "school":
        # A School combobox is a typeahead that shows only the first few of
        # thousands of schools, so the profile value is typed in to search.
        res.answer = value
        res.resolution_method = PROFILE_EXACT
    else:
        return
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
    # Non-compete questions are the candidate's to answer (a saved screening
    # answer covers the factual ones); "No" to "willing to sign one?" is a guess.
    if re.search(r"non-?\s?compete|restrictive\s+covenant|non-?\s?solicit", res.question or "", re.I):
        return
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
            # Whole words only: "no" sits inside "Snowflake", "know", "now".
            if re.search(r"\b(?:never|no|not\s+previously|none\s+of\s+the\s+above|neither)\b", o, re.I) and not re.match(
                r"\s*yes\b", o, re.I
            ):
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

# Attainment order for "Do you have a <level>?" questions; each pattern names a
# level and everything ranked at or above it satisfies a question asking for it.
_DEGREE_LEVELS = (
    (r"high\s*school|\bged\b|diploma|equivalen", 1),
    (r"associate", 2),
    (r"bachelor|\bb\.(?:s|a|e)\.|\bb\.?tech\b|undergraduate", 3),
    (r"master|\bm\.(?:s|a)\.|\bm\.?tech\b|\bmba\b|(?<!under)graduate\s+degree", 4),
    (r"ph\.?\s?d|doctor", 5),
)


def _degree_level(text: str) -> int | None:
    found = [level for pat, level in _DEGREE_LEVELS if re.search(pat, text or "", re.I)]
    return max(found) if found else None


def _option_at_degree_level(opts: list[str], degree: str) -> str | None:
    """eBay lists "Masters Degree or Equivalent" beside "MBA or Equivalent";
    a recorded "Master's Degree" is the option at its level that names it."""
    level = _degree_level(degree)
    if level is None:
        return None
    same = [o for o in opts if _degree_level(o) == level]
    root = re.match(r"[a-z]+", degree.lower())
    named = [o for o in same if root and root.group(0)[:6] in o.lower()]
    if len(named) == 1:
        return named[0]
    return same[0] if len(same) == 1 else None


def _resolve_degree_attainment(res: AnswerResolution, profile: dict, opts: list[str]) -> bool:
    """Answer "Do you have a <level> degree/diploma?" from the recorded education.

    Returns False (leaving `res` untouched) unless this is a yes/no question
    naming a level. A question that also names a field of study is answered only
    when the candidate's recorded discipline appears in it.
    """
    question = res.question or ""
    yes_no = _is_yes_no_options(opts) or (
        not opts and re.match(r"\s*(do|have|did|are)\b", question, re.I)
    )
    asked = _degree_level(question)
    if not yes_no or asked is None:
        return False
    entries = _education_entries(profile)
    held = [_degree_level(str(e.get("degree") or "")) for e in entries if e]
    held_level = max((h for h in held if h), default=None)
    if held_level is None:
        res.blocking_errors.append("No degree is recorded on the profile to answer this.")
        return True
    names_field = asked > 1 and re.search(r"\b(?:in|of)\s+(?:a\s+)?[a-z]+\s+(?:science|engineering|field|studies)", question, re.I)
    if names_field:
        disciplines = [str(e.get("discipline") or "").lower() for e in entries if e]
        if not any(d and d in question.lower() for d in disciplines):
            res.blocking_errors.append("The question names a field of study the recorded discipline does not match.")
            return True
    answer = "Yes" if held_level >= asked else "No"
    res.answer = _match_option(opts, answer) if opts else answer
    res.resolution_method = PROFILE_OPTION_MAPPING if opts else PROFILE_EXACT
    res.profile_key = "education[].degree"
    res.source_value = held_level
    res.confidence = 1.0
    return True


def _resolve_degree(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    if _resolve_degree_attainment(res, profile, opts):
        return
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

def _resolve_education_end_month(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_education_history(res, profile, opts, "end-month", 0)

def _resolve_education_start_month(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    _resolve_education_history(res, profile, opts, "start-month", 0)

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
            if re.search(
                r"\bn/?a\b|not\s+applicable|did\s+not\s+take|not\s+taken|\bnone\b|^\s*no\b|i\s+do\s+not\s+have|^\s*0\s*$",
                opt, re.I,
            ):
                res.answer = opt
                res.confidence = 1.0
                res.resolution_method = PROFILE_OPTION_MAPPING
                return
        # No "did not take" option: any other choice would state a score never recorded.
        res.blocking_errors.append("No offered option says the candidate has no test score to report.")
        res.confidence = 0.0
    else:
        res.answer = "N/A"
        res.confidence = 1.0
        res.resolution_method = PROFILE_EXACT

def _resolve_location_confirmation(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    q_low = (res.question or "").lower()
    profile_state = (profile.get("state") or "Washington").lower()
    profile_city = (profile.get("city") or "Auburn").lower()
    profile_metro = str(profile.get("metroArea") or "").lower()

    # Check if question is asking about living in US / candidate's region
    is_asking_us = any(k in q_low for k in ["united states", "u.s.", "usa", "in the us", "within the us", "north america"]) \
        or bool(_US_ABBREVIATION.search(res.question or ""))
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
        or (len(profile_metro) > 3 and re.search(rf"\b(?:greater\s+)?{re.escape(profile_metro)}\s+(?:area|metro)", q_low))
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

_TECH_WORD = re.compile(r"[a-z0-9][a-z0-9+#]*")

# Words that name no technology, so they neither prove nor disprove a claim.
_TECH_FILLER = frozenset("""
a an the and or of in on to for with using use used writing write building build developing develop designing
design working work architecting scaling maintaining running operating do does did you your have has had any
some experience experienced professional production commercial hands real world years year least more less
fewer than at most over under plus minimum strong solid deep familiarity familiar proficiency proficient
expertise knowledge code coding program programming language languages software engineering engineer
development based related similar equivalent environment environments large scale modern tools tooling
framework frameworks technologies technology stack tech platform platforms system systems service services
application applications app apps backend frontend full web cloud data distributed infrastructure team teams
level such as e g etc including like other both either this that these those role position our we please
describe explain if yes no how many much following which what is are be been currently previously recent
recently projects project products product solutions high quality assisted i my it its
one two three four five six seven eight nine ten eleven twelve fifteen twenty several
relevant related total overall qualified qualifying industry paid time part career early mid senior junior
entry post graduate individual contributor prior previous past current deliver delivering delivered shipping
practice practices automated automation testing test tests devops
excluding excluded internship internships advanced complex general full-time
phd degree specifically outside educational academic personal api apis
information needed required necessary computer science field fields object oriented
technical environment environments including highly transactional mission critical
multi user users architecture architectures
""".split())

# Practice questions a senior engineer answers truthfully in the affirmative;
# they name no technology to check against the evidence.
_PRACTICE_QUESTION = re.compile(
    r"experience\s+(?:using|with)\s+ai[\s-]*assisted|(?:github\s+copilot|cursor|chatgpt).*workflow|"
    r"reliable,\s*durable,\s*and\s*easily\s*maintained|coordinating\s+cross-functionally|"
    r"stakeholders\s+throughout\s+the\s+software\s+development\s+lifecycle",
    re.I,
)


def _career_tech_words() -> frozenset[str]:
    """Every word of every technology career.json records (skills index plus
    each project's technologies). Read-only; empty if career.json is absent."""
    try:
        from app.services.career_compiler.store import load_store

        store = load_store()
    except Exception:
        return frozenset()
    terms: set[str] = set()
    for values in (store.data.get("skills") or {}).values():
        if isinstance(values, list):
            terms.update(str(v) for v in values)
    for project in store.projects.values():
        terms.update(project.technologies)
    return frozenset(w for t in terms for w in _TECH_WORD.findall(t.lower()) if not w.isdigit())


def _unproven_tech_words(text: str) -> tuple[set[str], set[str]]:
    """(words career.json records, words it does not) among the question's
    technology words. Absence from the evidence is not proof of no experience,
    so an unproven word means "ask the candidate", never "No"."""
    known = _career_tech_words()
    words = {w for w in _TECH_WORD.findall(text.lower()) if not w.rstrip("+").isdigit() and w not in _TECH_FILLER}
    return words & known, words - known


def _resolve_tech_stack_experience(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    question = res.question or ""
    if _PRACTICE_QUESTION.search(question):
        yes = _match_option(opts, "Yes") if opts else "Yes"
        if yes:
            res.answer = yes
            res.confidence = 1.0
            res.resolution_method = PROFILE_OPTION_MAPPING if opts else PROFILE_EXACT
        return
    if opts and not _is_yes_no_options(opts):
        # A pick-one list of technologies: choose one the evidence records.
        for opt in opts:
            proven, unproven = _unproven_tech_words(opt)
            if proven and not unproven:
                res.answer = opt
                res.confidence = 1.0
                res.resolution_method = PROFILE_OPTION_MAPPING
                return
        res.blocking_errors.append("None of the offered technologies is recorded in career.json")
        return
    if re.match(r"\s*(?:which|what)\b", question, re.I):
        return
    _, unproven = _unproven_tech_words(question)
    if unproven:
        res.blocking_errors.append(
            "career.json records no experience with: " + ", ".join(sorted(unproven))
        )
        return
    res.answer = (_match_option(opts, "Yes") if opts else None) or "Yes"
    res.confidence = 1.0
    res.resolution_method = PROFILE_OPTION_MAPPING if opts else PROFILE_EXACT

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
    QuestionType.PHONE_DEVICE_TYPE: _resolve_phone_device_type,
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
    QuestionType.TIMEZONE_LOCATION: _resolve_timezone_location,
    QuestionType.EMPLOYER_COUNT: _resolve_employer_count,
    QuestionType.EMPLOYMENT_GAP: _resolve_employment_gap,
    QuestionType.ORIGINALITY_DECLARATION: _resolve_originality_declaration,
    QuestionType.SALARY: _resolve_salary,
    QuestionType.NOTICE_PERIOD: _resolve_notice_period,
    QuestionType.SMS_CONSENT: _resolve_sms_consent,
    QuestionType.MARKETING_CONSENT: _resolve_marketing_consent,
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
    QuestionType.EDUCATION_END_MONTH: _resolve_education_end_month,
    QuestionType.EDUCATION_START_MONTH: _resolve_education_start_month,
    QuestionType.GPA: _resolve_gpa,
    QuestionType.TEST_SCORE: _resolve_test_score,
    QuestionType.LOCATION_CONFIRMATION: _resolve_location_confirmation,
    QuestionType.TECH_STACK_EXPERIENCE: _resolve_tech_stack_experience,
    QuestionType.PREFERRED_LANGUAGE: _resolve_preferred_language,
    QuestionType.TRANSCRIPT: _resolve_transcript,
    QuestionType.LEGAL_AGE: lambda r, p, o: _resolve_legal_age(r, p, o),
}

def _resolve_legal_age(res: AnswerResolution, profile: dict, opts: list[str]) -> None:
    # "Are you under 18?" shares this type; the adult candidate's answer there is No.
    answer = "No" if re.search(r"\bunder\b", res.question or "", re.I) else "Yes"
    if opts:
        res.answer = _match_option(opts, answer) or answer
    else:
        res.answer = answer
    res.resolution_method = DETERMINISTIC_RULE
    res.confidence = 1.0

