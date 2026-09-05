"""Question Classifier — maps every form field to a semantic QuestionType.

This replaces ad-hoc label matching scattered across the executor and adapters
with a centralized, testable classification system.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any


class QuestionType(str, Enum):
    """Semantic type for every form field encountered during application."""

    # ── Identity ──
    FIRST_NAME = "FIRST_NAME"
    LAST_NAME = "LAST_NAME"
    FULL_NAME = "FULL_NAME"
    PREFERRED_NAME = "PREFERRED_NAME"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    PHONE_COUNTRY = "PHONE_COUNTRY"

    # ── Location ──
    CITY = "CITY"
    STATE = "STATE"
    COUNTRY = "COUNTRY"
    ZIP = "ZIP"
    ADDRESS = "ADDRESS"
    LOCATION = "LOCATION"

    # ── Professional ──
    CURRENT_COMPANY = "CURRENT_COMPANY"
    CURRENT_TITLE = "CURRENT_TITLE"
    YEARS_EXPERIENCE = "YEARS_EXPERIENCE"
    LINKEDIN = "LINKEDIN"
    GITHUB = "GITHUB"
    WEBSITE = "WEBSITE"

    # ── Documents ──
    RESUME = "RESUME"
    COVER_LETTER = "COVER_LETTER"
    TRANSCRIPT = "TRANSCRIPT"

    # ── Education ──
    SCHOOL = "SCHOOL"
    DEGREE = "DEGREE"
    DISCIPLINE = "DISCIPLINE"
    GPA = "GPA"
    TEST_SCORE = "TEST_SCORE"

    # ── Work Authorization (each is a DISTINCT concept) ──
    WORK_AUTHORIZED = "WORK_AUTHORIZED"
    SPONSORSHIP_REQUIRED = "SPONSORSHIP_REQUIRED"
    PERMANENT_WORK_AUTHORIZATION = "PERMANENT_WORK_AUTHORIZATION"
    CITIZENSHIP = "CITIZENSHIP"
    EXPORT_CONTROL = "EXPORT_CONTROL"

    # ── Security ──
    SECURITY_CLEARANCE_ELIGIBILITY = "SECURITY_CLEARANCE_ELIGIBILITY"
    SECURITY_CLEARANCE_LEVEL = "SECURITY_CLEARANCE_LEVEL"

    # ── Demographics (each is DISTINCT — never cross-contaminate) ──
    GENDER = "GENDER"
    PRONOUNS = "PRONOUNS"
    TRANSGENDER = "TRANSGENDER"
    SEXUAL_ORIENTATION = "SEXUAL_ORIENTATION"
    ETHNICITY_HISPANIC_LATINO = "ETHNICITY_HISPANIC_LATINO"
    RACE = "RACE"
    VETERAN_STATUS = "VETERAN_STATUS"
    DISABILITY = "DISABILITY"

    # ── Compliance / Consent ──
    SMS_CONSENT = "SMS_CONSENT"
    PRIVACY_CONSENT = "PRIVACY_CONSENT"
    ACCURACY_CONFIRMATION = "ACCURACY_CONFIRMATION"
    BACKGROUND_CHECK = "BACKGROUND_CHECK"
    COMPANY_HISTORY = "COMPANY_HISTORY"

    # ── Availability ──
    NOTICE_PERIOD = "NOTICE_PERIOD"
    RELOCATE = "RELOCATE"
    SALARY = "SALARY"

    # ── Miscellaneous ──
    HOW_HEARD = "HOW_HEARD"
    ENGLISH_PROFICIENCY = "ENGLISH_PROFICIENCY"
    LOCATION_CONFIRMATION = "LOCATION_CONFIRMATION"
    TECH_STACK_EXPERIENCE = "TECH_STACK_EXPERIENCE"

    # ── Free Text (sub-classified by intent) ──
    FREE_TEXT_EXPERIENCE = "FREE_TEXT_EXPERIENCE"
    FREE_TEXT_INTEREST = "FREE_TEXT_INTEREST"
    FREE_TEXT_WHY_COMPANY = "FREE_TEXT_WHY_COMPANY"
    FREE_TEXT_BLOG_POST = "FREE_TEXT_BLOG_POST"
    FREE_TEXT_PROJECT = "FREE_TEXT_PROJECT"
    FREE_TEXT_TECHNICAL = "FREE_TEXT_TECHNICAL"

    # ── Fallback ──
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


# Fields where LLM must NEVER invent answers — require profile match only.
SENSITIVE_FACTUAL_TYPES: frozenset[QuestionType] = frozenset({
    QuestionType.WORK_AUTHORIZED,
    QuestionType.SPONSORSHIP_REQUIRED,
    QuestionType.PERMANENT_WORK_AUTHORIZATION,
    QuestionType.CITIZENSHIP,
    QuestionType.EXPORT_CONTROL,
    QuestionType.SECURITY_CLEARANCE_ELIGIBILITY,
    QuestionType.SECURITY_CLEARANCE_LEVEL,
    QuestionType.GENDER,
    QuestionType.PRONOUNS,
    QuestionType.TRANSGENDER,
    QuestionType.SEXUAL_ORIENTATION,
    QuestionType.ETHNICITY_HISPANIC_LATINO,
    QuestionType.RACE,
    QuestionType.VETERAN_STATUS,
    QuestionType.DISABILITY,
    QuestionType.LOCATION,
    QuestionType.CITY,
    QuestionType.STATE,
    QuestionType.PHONE,
    QuestionType.EMAIL,
    QuestionType.FIRST_NAME,
    QuestionType.LAST_NAME,
})


# ── Classification patterns ──────────────────────────────────────────────────
# Order matters: more specific patterns MUST come before general ones.
# E.g., "permanent authorization" must match before "authorized to work".

_CLASSIFICATION_RULES: list[tuple[QuestionType, list[str]]] = [
    # ── Work Auth (specific before general) ──
    (QuestionType.PERMANENT_WORK_AUTHORIZATION, [
        r"permanent\s+(work\s+)?authoriz",
        r"permanent\s+right\s+to\s+work",
        r"do you have permanent\s+(work\s+)?authoriz",
        r"permanent\s+legal\s+authoriz",
    ]),
    (QuestionType.EXPORT_CONTROL, [
        r"export\s+control",
        r"\bitar\b",
        r"\bear\b(?!.*year)",
        r"u\.s\.\s*person",
        r"export\s+administration",
        r"export\s+regulation",
    ]),
    (QuestionType.CITIZENSHIP, [
        r"citizen(ship)?(?!.*clear)",
        r"national(ity)?(?!.*security)",
        r"are you a.{0,30}citizen",
    ]),
    (QuestionType.SPONSORSHIP_REQUIRED, [
        r"sponsor",
        r"visa\s+sponsorship",
        r"require\s+sponsorship",
        r"need\s+sponsorship",
        r"immigration",
        r"\bh-?1b\b",
        r"require\s+visa",
    ]),
    (QuestionType.WORK_AUTHORIZED, [
        r"authorized\s+to\s+work",
        r"right\s+to\s+work",
        r"eligible\s+to\s+work",
        r"legally\s+(authorized|able)\s+to\s+work",
        r"work\s+authoriz",
        r"work\s+status",
        r"permit\s+to\s+work",
        r"u\.s\.\s*work\s+authoriz",
    ]),

    # ── Security Clearance ──
    (QuestionType.SECURITY_CLEARANCE_ELIGIBILITY, [
        r"clearance\s*eligib",
        r"eligib.*clearance",
        r"eligibility\s+to\s+obtain.*clearance",
        r"able\s+to\s+obtain.*security\s+clearance",
        r"obtain\s+and\s+maintain.*clearance",
    ]),
    (QuestionType.SECURITY_CLEARANCE_LEVEL, [
        r"clearance\s*level",
        r"security\s+clearance.*held",
        r"current.*security\s+clearance",
        r"highest.*clearance",
        r"level.*clearance.*held",
    ]),

    # ── Demographics (DISTINCT categories — order matters) ──
    (QuestionType.ETHNICITY_HISPANIC_LATINO, [
        r"\bhispanic\b",
        r"\blatino\b",
        r"\blatina\b",
        r"\blatinx\b",
        r"hispanic\s*/?\s*latino",
    ]),
    (QuestionType.RACE, [
        r"please\s+identify\s+your\s+race",
        r"\brace\b",
        r"racial",
        r"ethnic\s+(background|identity)",
        r"ethnicit",
    ]),
    (QuestionType.TRANSGENDER, [r"transgender"]),
    (QuestionType.SEXUAL_ORIENTATION, [r"sexual\s+orient"]),
    (QuestionType.GENDER, [r"\bgender\b", r"\bsex\b(?!ual)"]),
    (QuestionType.PRONOUNS, [r"\bpronoun"]),
    (QuestionType.VETERAN_STATUS, [
        r"veteran",
        r"military\s+service",
        r"armed\s+forces",
        r"protected\s+veteran",
    ]),
    (QuestionType.DISABILITY, [
        r"disabilit",
        r"\bada\b",
        r"physical\s+or\s+mental\s+impairment",
    ]),

    # ── Identity ──
    (QuestionType.FIRST_NAME, [r"first[\s_-]*name", r"^fname$", r"given[\s_-]*name"]),
    (QuestionType.LAST_NAME, [r"last[\s_-]*name", r"^lname$", r"family[\s_-]*name", r"surname"]),
    (QuestionType.FULL_NAME, [r"full\s*name", r"^name\s*\*?$", r"legal\s*name", r"applicant\s*name"]),
    (QuestionType.PREFERRED_NAME, [r"preferred\s*name", r"nickname", r"what.*call\s*you"]),
    (QuestionType.EMAIL, [r"e-?mail"]),
    (QuestionType.PHONE_COUNTRY, [r"country\s*code", r"dial\s*code"]),
    (QuestionType.PHONE, [r"phone", r"telephone", r"mobile", r"\btel\b", r"cell"]),

    # ── Location ──
    (QuestionType.STATE, [
        r"select\s+the\s+state",
        r"state\s+in\s+which",
        r"state\s+(of\s+)?residen",
        r"state\s+you\s+reside",
        r"current\s+state",
        r"\bstate\b(?!.*ment)",
        r"\bprovince\b",
    ]),
    (QuestionType.CITY, [r"\bcity\b", r"municipality"]),
    (QuestionType.ZIP, [r"\bzip\b", r"postal\s*code", r"postcode"]),
    (QuestionType.COUNTRY, [r"\bcountry\b(?!.*code)"]),
    (QuestionType.ADDRESS, [r"address", r"street"]),
    (QuestionType.LOCATION_CONFIRMATION, [
        r"is\s+your\s+current\s+location",
        r"currently\s+located\s+in",
        r"are\s+you\s+(currently\s+)?based\s+in",
        r"current\s+country\s+of\s+residence",
        r"do\s+you\s+live\s+in\s+(one\s+of\s+the\s+following\s+)?(states|countries|locations)",
        r"do\s+you\s+(currently\s+)?reside\s+in",
        r"are\s+you\s+located\s+in",
        r"live\s+in\s+one\s+of\s+the\s+following",
        r"based\s+in\s+any\s+of\s+these",
    ]),
    (QuestionType.LOCATION, [
        r"location",
        r"city.*state",
        r"where.*(live|located)",
        r"work\s+location",
    ]),

    # ── Professional ──
    (QuestionType.CURRENT_COMPANY, [
        r"^(what\s+is\s+your\s+)?current\s*(company|employer)",
        r"name\s+of\s+your\s+current\s*(or\s+most\s+recent)?\s*(company|employer)",
        r"most\s+recent.*(company|employer)",
        r"company\s*name",
        r"where.*most\s+recently\s+worked",
        r"organization",
    ]),
    (QuestionType.CURRENT_TITLE, [
        r"current\s*(job\s*)?title",
        r"current\s*role",
        r"most\s*recent\s*title",
        r"position\s*title",
        r"headline",
    ]),
    (QuestionType.YEARS_EXPERIENCE, [
        r"years\s*(of\s*)?experience",
        r"experience\s*level",
        r"how\s*many\s*years",
        r"hands-on\s*experience",
    ]),
    (QuestionType.TECH_STACK_EXPERIENCE, [
        r"which\s+of\s+the\s+following.*(experience|familiar|use)",
        r"which\s+technolog",
        r"technologies.*experience",
    ]),
    (QuestionType.LINKEDIN, [r"linkedin"]),
    (QuestionType.GITHUB, [r"github"]),
    (QuestionType.WEBSITE, [r"portfolio", r"website", r"personal\s*site"]),

    # ── Documents ──
    (QuestionType.RESUME, [r"resume", r"\bcv\b", r"curriculum\s*vitae"]),
    (QuestionType.COVER_LETTER, [r"cover\s*letter", r"writing\s*sample"]),
    (QuestionType.TRANSCRIPT, [r"transcript"]),

    # ── Education ──
    (QuestionType.SCHOOL, [r"school", r"university", r"college", r"institution"]),
    (QuestionType.DEGREE, [r"degree", r"level\s*of\s*education", r"highest\s*degree"]),
    (QuestionType.DISCIPLINE, [r"major", r"discipline", r"field\s*of\s*study"]),
    (QuestionType.GPA, [r"\bgpa\b", r"grade\s*point\s*average"]),
    (QuestionType.TEST_SCORE, [
        r"\bact\s*score",
        r"\bsat\s*score",
        r"\bgre\s*score",
        r"\bgmat\s*score",
        r"test\s*score",
    ]),
    (QuestionType.SECURITY_CLEARANCE_LEVEL, [
        r"security\s*clearance",
        r"active.*clearance",
    ]),

    # ── Availability / Compliance ──
    (QuestionType.SALARY, [r"salary", r"compensation", r"desired\s*pay", r"expected\s*salary"]),
    (QuestionType.NOTICE_PERIOD, [r"notice\s*period", r"start\s*date", r"available\s*to\s*start", r"how\s*soon"]),
    (QuestionType.RELOCATE, [r"relocat", r"willing\s*to\s*relocat", r"local\s+to"]),
    (QuestionType.SMS_CONSENT, [r"text\s*message", r"\bsms\b", r"consent.*(text|message)"]),
    (QuestionType.HOW_HEARD, [
        r"how\s*did\s*you\s*hear",
        r"how\s*did\s*you\s*find\s*us",
        r"where\s*did\s*you.*hear",
        r"learn\s*about.*employer",
        r"how.*first\s+learn",
    ]),
    (QuestionType.PRIVACY_CONSENT, [
        r"privacy\s*policy",
        r"candidate\s*privacy",
        r"recruitment\s*privacy",
        r"acknowledge.*read\s+and\s+understand",
        r"consent\s+to.*process",
    ]),
    (QuestionType.ENGLISH_PROFICIENCY, [r"english\s*proficiency", r"english\s*language", r"fluent\s*in\s*english"]),
    (QuestionType.BACKGROUND_CHECK, [r"background\s*check"]),
    (QuestionType.COMPANY_HISTORY, [
        r"previously\s*(worked|employed|consulted|been\s+employed)",
        r"previously\s+been\s+employed",
        r"worked\s+at\s+or\s+consulted",
        r"prior\s+employment",
        r"employment\s+history",
        r"have\s+you\s+(ever|previously)\s*(worked|been\s+employed)\s*(at|for)",
        r"interview(ed)?\s*with",
        r"former\s*employee",
        r"conflict\s*of\s*interest",
        r"relative.*employed",
        r"family\s+member",
        r"employment\s+agreement",
        r"non[- ]?compete",
        r"restrictive\s+covenant",
        r"post-employment\s+restriction",
    ]),
    (QuestionType.ACCURACY_CONFIRMATION, [
        r"essential\s+functions",
        r"reasonable\s+accommodation",
        r"perform.*essential.*functions",
        r"double.?check\s+all",
        r"accuracy\s+is\s+crucial",
        r"errors\s+or\s+omissions",
        r"\baccurate\b",
    ]),
]

# ── Free-text intent patterns ─────────────────────────────────────────────────

_FREE_TEXT_INTENT_RULES: list[tuple[QuestionType, list[str]]] = [
    (QuestionType.FREE_TEXT_BLOG_POST, [
        r"blog\s*post",
        r"favorite\s+article",
        r"share.*(blog|article|post)",
        r"technical\s+writing",
    ]),
    (QuestionType.FREE_TEXT_WHY_COMPANY, [
        r"why.*(company|us|join|interested|apply|this\s+role)",
        r"what\s+excites\s+you",
        r"motivat.*(apply|join|role)",
    ]),
    (QuestionType.FREE_TEXT_PROJECT, [
        r"project\s+you.*(built|worked|proud)",
        r"describe\s+a\s+project",
        r"side\s+project",
    ]),
    (QuestionType.FREE_TEXT_TECHNICAL, [
        r"technical\s+(challenge|problem|question)",
        r"coding\s+(challenge|test)",
        r"system\s+design",
    ]),
    (QuestionType.FREE_TEXT_INTEREST, [
        r"interest",
        r"hobby",
        r"passion",
        r"what\s+do\s+you\s+enjoy",
    ]),
    (QuestionType.FREE_TEXT_EXPERIENCE, [
        r"experience",
        r"background",
        r"tell\s+us\s+about\s+yourself",
        r"describe\s+your",
    ]),
]


def classify_question(
    question_text: str,
    field_id: str = "",
    options: list[str] | None = None,
) -> QuestionType:
    """Classify a form field into its semantic QuestionType.

    Uses regex patterns in priority order.  More specific patterns
    (e.g. PERMANENT_WORK_AUTHORIZATION) are checked before general
    ones (e.g. WORK_AUTHORIZED).
    """
    if not question_text and not field_id:
        return QuestionType.UNKNOWN

    text = f"{question_text} {field_id}".lower().strip()

    for qtype, patterns in _CLASSIFICATION_RULES:
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return qtype

    return QuestionType.UNKNOWN


def classify_free_text_intent(question_text: str) -> QuestionType:
    """Sub-classify a free-text / open-ended question by intent.

    Call this AFTER classify_question returns UNKNOWN for a textarea
    or long-text field to determine the appropriate prompt template.
    """
    text = question_text.lower().strip()
    for qtype, patterns in _FREE_TEXT_INTENT_RULES:
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return qtype
    return QuestionType.FREE_TEXT_EXPERIENCE  # safe default for generic questions


def is_sensitive_factual(qtype: QuestionType) -> bool:
    """Whether this question type requires deterministic profile answers only."""
    return qtype in SENSITIVE_FACTUAL_TYPES
