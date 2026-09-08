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
    ADDRESS_LINE_2 = "ADDRESS_LINE_2"
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
    SANCTIONED_COUNTRIES = "SANCTIONED_COUNTRIES"
    AI_AGENT_DISCLOSURE = "AI_AGENT_DISCLOSURE"
    GOVERNMENT_CONFLICT = "GOVERNMENT_CONFLICT"

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
    FIRST_GEN_PROFESSIONAL = "FIRST_GEN_PROFESSIONAL"

    # ── Compliance / Consent ──
    SMS_CONSENT = "SMS_CONSENT"
    PRIVACY_CONSENT = "PRIVACY_CONSENT"
    ACCURACY_CONFIRMATION = "ACCURACY_CONFIRMATION"
    BACKGROUND_CHECK = "BACKGROUND_CHECK"
    COMPANY_HISTORY = "COMPANY_HISTORY"

    # ── Availability ──
    NOTICE_PERIOD = "NOTICE_PERIOD"
    RELOCATE = "RELOCATE"
    WORK_ARRANGEMENT = "WORK_ARRANGEMENT"
    TIMEZONE_AVAILABILITY = "TIMEZONE_AVAILABILITY"
    SALARY = "SALARY"

    # ── Miscellaneous ──
    HOW_HEARD = "HOW_HEARD"
    COMPANY_FAMILIARITY = "COMPANY_FAMILIARITY"
    ENGLISH_PROFICIENCY = "ENGLISH_PROFICIENCY"
    LOCATION_CONFIRMATION = "LOCATION_CONFIRMATION"
    TECH_STACK_EXPERIENCE = "TECH_STACK_EXPERIENCE"
    PREFERRED_LANGUAGE = "PREFERRED_LANGUAGE"

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
    QuestionType.FIRST_GEN_PROFESSIONAL,
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
    # OFAC-sanctioned-country questions ("citizen or resident of Cuba, Iran,
    # North Korea, Syria...") contain the word "citizen" and would otherwise
    # fall into the generic CITIZENSHIP pattern below, which answers based on
    # US citizenship status — a completely different question that only
    # coincidentally produces the right answer for candidates who aren't US
    # citizens. Must be checked first since it's more specific. The named
    # countries are standardized OFAC language, safe to match directly.
    (QuestionType.SANCTIONED_COUNTRIES, [
        r"\bcrimea\b",
        r"\bcuba\b.{0,60}\biran\b",
        r"\biran\b.{0,60}\bnorth korea\b",
        r"\bnorth korea\b.{0,60}\bsyria\b",
        r"sanctioned\s+countr",
        r"comprehensively\s+sanctioned",
    ]),
    # Narrow, deliberately strict: only matches a question that gives an
    # explicit decision rule for AI agents specifically ("select Yes if you
    # are an AI agent... select Not Applicable if you are a human"). This is
    # a factual question this system can answer with complete certainty and
    # total honesty — it genuinely is an AI agent submitting the
    # application. Does NOT match the more open-ended "was this application
    # prepared with AI assistance?" phrasing some companies use instead,
    # which is deliberately left for the candidate to answer themselves.
    (QuestionType.AI_AGENT_DISCLOSURE, [
        r"if\s+you\s+are\s+an\s+ai\s+agent",
        r"ai\s+agent\s+applying\s+on\s+behalf",
        # "Was this application prepared or submitted in whole or in part by
        # an AI system, language model, or automated agent?" — a direct
        # factual yes/no about whether AI was involved, not the vaguer
        # "prepared WITH AI assistance" framing (a matter of degree) still
        # deliberately left unanswered above.
        r"prepared\s+or\s+submitted.{0,40}\bby\s+an?\s+ai\b",
        r"ai\s+system,?\s+language\s+model,?\s+or\s+automated\s+agent",
        r"use\s+ai[\s-]*powered\s+tools\s+during\s+our\s+evaluation",
        r"simulate\s+real[\s-]*world\s+workflows",
    ]),
    # Must come before CITIZENSHIP/EXPORT_CONTROL below: contains neither
    # "citizen" nor "export control" verbatim, but is the same "answer No,
    # this doesn't apply to me" compliance-checkbox category already
    # answered in the profile's screeningAnswers for other companies
    # (Anduril's conflict-of-interest question is the same underlying ask).
    (QuestionType.GOVERNMENT_CONFLICT, [
        r"government\s+(employee|official)",
        r"procurement\s+or\s+contract\s+award",
        r"oversight.*(business|company|contract)",
        r"conflict\s*of\s*interest",
    ]),
    # Work authorization questions that mention country ("authorized to work in the country outlined", etc.)
    # must be classified as WORK_AUTHORIZED rather than falling into CITIZENSHIP.
    (QuestionType.WORK_AUTHORIZED, [
        r"authorized\s+to\s+work",
        r"authorization\s+to\s+work",
        r"right\s+to\s+work",
        r"eligible\s+to\s+work",
        r"legally\s+(authorized|able)\s+to\s+work",
        r"work\s+authoriz",
        r"work\s+status",
        r"permit\s+to\s+work",
        r"u\.s\.\s*work\s+authoriz",
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
    (QuestionType.FIRST_GEN_PROFESSIONAL, [
        r"first[\s-]*generation\s+professional",
        r"first[\s-]*generation\s+college",
    ]),

    # ── Identity ──
    (QuestionType.PREFERRED_NAME, [r"preferred\s*(first\s*)?name", r"preferred\s*name", r"nickname", r"what.*call\s*you"]),
    (QuestionType.FIRST_NAME, [r"first[\s_-]*name", r"^fname$", r"given[\s_-]*name"]),
    (QuestionType.LAST_NAME, [r"last[\s_-]*name", r"^lname$", r"family[\s_-]*name", r"surname"]),
    (QuestionType.FULL_NAME, [r"full\s*name", r"^name\s*\*?$", r"legal\s*name", r"applicant\s*name"]),
    # Checked before EMAIL: a long consent sentence ("contact you via SMS or
    # WhatsApp... via the email you provided") mentions "email" only in
    # passing, but the bare EMAIL pattern below matches on that substring
    # anywhere in the text and would otherwise intercept this question
    # first, well before it ever reaches SMS_CONSENT's own patterns.
    (QuestionType.SMS_CONSENT, [r"text\s*message", r"\bsms\b", r"whatsapp", r"consent.*(text|message)"]),
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
    # A secondary address line (apartment/suite/unit) is a different question
    # from the street address itself — must be checked first, since "address"
    # and "street" both match it too and would otherwise duplicate line 1's
    # value onto it.
    (QuestionType.ADDRESS_LINE_2, [
        r"address\s*(line\s*)?2\b",
        r"street\s*(address\s*)?2\b",
        r"\bapt\b|\bapartment\b|\bsuite\b|\bunit\b",
    ]),
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
    # Must come before LOCATION below: "Are you willing to relocate to one of
    # our hub locations...?" contains the bare word "locations", which
    # LOCATION's own unqualified r"location" pattern would otherwise match
    # first, misclassifying a relocation Yes/No question as a plain
    # city/address field and leaving it permanently unresolved.
    (QuestionType.RELOCATE, [r"relocat", r"willing\s*to\s*relocat", r"local\s+to"]),
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
        r"early\s+career",
    ]),
    (QuestionType.TECH_STACK_EXPERIENCE, [
        r"which\s+of\s+the\s+following.*(experience|familiar|use)",
        r"which\s+technolog",
        r"technologies.*experience",
    ]),
    (QuestionType.PREFERRED_LANGUAGE, [
        r"preferred\s+programming\s+language",
        r"favorite\s+programming\s+language",
        r"which\s+programming\s+language.*prefer",
    ]),
    (QuestionType.LINKEDIN, [r"linkedin"]),
    (QuestionType.GITHUB, [r"github"]),
    (QuestionType.WEBSITE, [
        r"portfolio",
        r"website",
        r"personal\s*site",
        r"other\s*links?",
        r"other\s*websites?",
        r"additional\s*links?",
        r"additional\s*websites?",
        r"relevant\s*links?",
        r"other\s*social",
    ]),

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
    (QuestionType.WORK_ARRANGEMENT, [
        r"hybrid",
        r"\bremote\b",
        r"on-?site",
        r"in[- ]?person",
        r"work\s*from\s*home",
        r"\d+\s*days?\s*(a|per|/)\s*week.*(office|in-?person|on-?site)",
        r"(office|in-?person|on-?site).*\d+\s*days?\s*(a|per|/)\s*week",
        r"days?\s*(in|per)\s*(the\s*)?office",
        r"work\s*arrangement",
        r"working\s*environment",
    ]),
    (QuestionType.TIMEZONE_AVAILABILITY, [
        r"time\s*zone",
        r"eastern\s*time|central\s*time|pacific\s*time|mountain\s*time",
        r"\b(est|edt|cst|cdt|pst|pdt|mst|mdt|utc|gmt)\b.*(hours|time|work|shift)",
        r"work(ing)?\s*hours",
        r"core\s*hours",
        r"overlap.*hours",
    ]),
    (QuestionType.ENGLISH_PROFICIENCY, [
        r"english\s*level",
        r"english\s*proficiency",
        r"level\s*of\s*english",
        r"fluency\s*in\s*english",
    ]),
    (QuestionType.HOW_HEARD, [
        r"how\s*did\s*you\s*hear",
        r"how\s*did\s*you\s*find\s*us",
        r"where\s*did\s*you.*hear",
        r"learn\s*about.*employer",
        r"how.*first\s+learn",
    ]),
    (QuestionType.COMPANY_FAMILIARITY, [
        r"how\s+familiar\s+were\s+you",
        r"familiarity\s+with\s+(the\s+)?company",
    ]),
    (QuestionType.PRIVACY_CONSENT, [
        r"privacy\s*policy",
        r"candidate\s*privacy",
        r"recruitment\s*privacy",
        r"applicant\s*privacy",
        r"privacy\s*acknowledg",
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
        r"have\s+you\s+(ever\s+)?been\s+employed\s*(by|at|for)",
        r"have\s+you\s+(ever\s+)?worked\s*(at|for)",
        r"worked\s+for\s+\w+\s+as\s+an\s+employee,?\s+intern",
        r"employed\s+by\s+\w+\s+before",
        r"(ever,?\s*or\s+are\s+you\s+currently\s+)?working\s+at\s+\w+\s+in\s+any\s+capacity",
        r"currently\s+working\s+(at|for)\s+\w+",
        r"interview(ed)?\s*(with|at|by)",
        r"former\s*employee",
        r"conflict\s*of\s*interest",
        r"relative.*employed",
        r"family\s+member",
        r"related\s+to,?\s+anyone",
        r"know,?\s*or\s*are\s+you\s+related",
        r"know\s+anyone\s+(who\s+)?(works|working)",
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


# Free-text location types make no sense for a field whose actual options are
# a plain Yes/No choice. Without this guard, a Yes/No question that happens to
# name a place (e.g. "...in San Francisco or Redwood City?") matches the CITY
# pattern on the word "City" and gets misclassified as a city-name field —
# observed live: the resolver then tried to answer a hybrid-schedule Yes/No
# question with "Auburn" (the candidate's city), typed it into the combobox,
# and left leftover text there that DOM verification flagged nonsensically.
_LOCATION_FAMILY = frozenset({
    QuestionType.CITY,
    QuestionType.STATE,
    QuestionType.COUNTRY,
    QuestionType.ZIP,
    QuestionType.ADDRESS,
    QuestionType.LOCATION,
    QuestionType.LOCATION_CONFIRMATION,
})

_BOOLEAN_OPTION_WORDS = frozenset({
    "yes", "no", "true", "false", "n/a",
    "decline to answer", "prefer not to answer",
    "i don't wish to answer", "i do not wish to answer",
})


def _is_boolean_options(options: list[str] | None) -> bool:
    """True if `options` is a plain Yes/No (optionally with a decline choice)."""
    if not options:
        return False
    normalized = {o.strip().lower() for o in options if o.strip()}
    if not normalized or len(normalized) > 3:
        return False
    return normalized.issubset(_BOOLEAN_OPTION_WORDS) and (
        "yes" in normalized or "no" in normalized
    )


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
    is_boolean = _is_boolean_options(options)

    for qtype, patterns in _CLASSIFICATION_RULES:
        if is_boolean and qtype in _LOCATION_FAMILY:
            continue
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return qtype

    # Rescue for vague EEOC labels like "I identify as:*" that carry no
    # keyword of their own — some Greenhouse forms phrase the transgender-
    # identity question this generically, distinguishable only by its
    # option set ("Cisgender"/"Transgender" never appear as options for any
    # other question type, so this is unambiguous).
    if options:
        normalized_opts = {o.strip().lower() for o in options if o.strip()}
        if "cisgender" in normalized_opts and "transgender" in normalized_opts:
            return QuestionType.TRANSGENDER

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
