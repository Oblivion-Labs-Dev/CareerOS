"""JobPilot — Role Classification & Resume Matching.

Shared module used by both the scraper (title filtering) and auto-apply
(role-based resume selection). Single source of truth for role taxonomy.

Role categories:
  pm       — Product Manager, APM, Senior PM, Group PM, Director of Product, VP Product
  tpm      — Technical Program Manager, Program Manager, Agile PM
  product  — Product Analyst, Product Strategy, Product Ops, Product Marketing, Product Owner
  ux       — UX Designer, Product Designer, UX Researcher, UI/UX
  swe      — Software Engineer, SDE, Frontend/Backend/Fullstack Engineer
  presales — Solutions Engineer, Sales Engineer, Solutions Architect
  hw       — Hardware Engineer, VLSI, ASIC, Electrical Engineer (future)
"""

import re
from functools import lru_cache

# ── Role Patterns ──────────────────────────────────────────────────────────────
# Order matters: more specific patterns first within each category.
# classify_role() checks categories top-to-bottom and returns the FIRST match.

ROLE_PATTERNS: dict[str, list[str]] = {
    "pm": [
        r"\btechnical\s+product\s+manager\b",
        r"\bassociate\s+product\s+manager\b",
        r"\bsenior\s+product\s+manager\b",
        r"\bstaff\s+product\s+manager\b",
        r"\bgroup\s+product\s+manager\b",
        r"\bprincipal\s+product\s+manager\b",
        r"\bdirector.*product\s+manage",
        r"\bvp.*product\b",
        r"\bhead\s+of\s+product\b",
        r"\bproduct\s+manager\b",
        r"\bproduct\s+lead\b",
        r"\bproduct\s+owner\b",
        r"\bapm\b",
    ],
    "tpm": [
        r"\btechnical\s+program\s+manager\b",
        r"\bsenior\s+program\s+manager\b",
        r"\bstaff\s+program\s+manager\b",
        r"\bprogram\s+manager\b",
        r"\btpm\b",
        r"\bagile\s+program\s+manager\b",
        r"\bproject\s+manager\b",
    ],
    "product": [
        r"\bproduct\s+analyst\b",
        r"\bproduct\s+strategy\b",
        r"\bproduct\s+ops\b",
        r"\bproduct\s+operations\b",
        r"\bproduct\s+marketing\s+manager\b",
    ],
    "ux": [
        r"\bux\s+designer\b",
        r"\bux\s+design\b",
        r"\bux\s+researcher\b",
        r"\bux\s+research\b",
        r"\buser\s+experience\b",
        r"\bproduct\s+designer\b",
        r"\bux/ui\b",
        r"\bui/ux\b",
        r"\binteraction\s+designer\b",
        r"\bvisual\s+designer\b",
    ],
    "swe": [
        r"\bsoftware\s+development\s+engineer\b",
        r"\bsoftware\s+engineer\b",
        r"\bfrontend\s+engineer\b",
        r"\bbackend\s+engineer\b",
        r"\bfull[\s\-]?stack\s+engineer\b",
        r"\bplatform\s+engineer\b",
        r"\bsde\b",
        r"\bswe\b",
        r"\bml\s+engineer\b",
        r"\bmachine\s+learning\s+engineer\b",
        r"\bdata\s+engineer\b",
        r"\bdevops\s+engineer\b",
        r"\bsite\s+reliability\s+engineer\b",
        r"\bsre\b",
        r"\binfrastructure\s+engineer\b",
    ],
    "presales": [
        r"\bpre[\-\s]?sales\b",
        r"\bsolutions\s+engineer\b",
        r"\bsolutions\s+consultant\b",
        r"\bsales\s+engineer\b",
        r"\bproduct\s+consultant\b",
        r"\bsolutions\s+architect\b",
    ],
    "hw": [
        r"\bhardware\s+engineer\b",
        r"\bvlsi\b",
        r"\basic\b",
        r"\bfpga\b",
        r"\belectrical\s+engineer\b",
        r"\bembedded\s+engineer\b",
        r"\bfirmware\s+engineer\b",
        r"\bchip\s+design\b",
        r"\bsilicon\b",
    ],
}

# Human-readable labels for each role category
ROLE_LABELS: dict[str, str] = {
    "pm": "Product Manager",
    "tpm": "Program Manager / TPM",
    "product": "Product (Analyst/Strategy/Ops)",
    "ux": "UX / Product Designer",
    "swe": "Software Engineer",
    "presales": "Pre-Sales / Solutions",
    "hw": "Hardware / Embedded",
}

# Which resume tag to use for each role category
# This maps role → resume tag. Multiple roles can share a resume.
ROLE_RESUME_MAP: dict[str, str] = {
    "pm": "pm",
    "tpm": "tpm",
    "product": "pm",        # Product roles use PM resume
    "ux": "ux",
    "swe": "swe",
    "presales": "pm",       # Pre-sales uses PM resume as fallback
    "hw": "hw",
}


# ── Negative Patterns — titles that look like matches but aren't ──────────────
# These override any positive match. A "Marketing Director" might match a loose
# "product marketing" pattern, but we don't want it. Same for legal, finance,
# accounting, VLSI, etc. titles that have zero relevance.

EXCLUDED_TITLE_PATTERNS: list[str] = [
    # Legal / compliance
    r"\bcounsel\b", r"\battorney\b", r"\blawyer\b", r"\blegal\b",
    r"\bcompliance\s+officer\b", r"\bparalegal\b",
    # Finance / accounting / treasury (not product)
    r"\bfinancial\s+analyst\b", r"\bfp&a\b", r"\baccountant\b",
    r"\baccounting\b", r"\bauditor\b", r"\btreasury\b", r"\btax\b",
    r"\bcontroller\b", r"\bbookkeeper\b", r"\bpayroll\b",
    r"\bfinancial\s+controller\b", r"\bfinance\s+manager\b",
    r"\brevenue\s+analyst\b",
    # Pure marketing / sales (not product marketing manager)
    r"\baccount\s+(?:based\s+)?marketing\s+director\b",
    r"\bmarketing\s+director\b", r"\bmarketing\s+coordinator\b",
    r"\bfield\s+marketing\b", r"\bbrand\s+marketing\b",
    r"\bdemand\s+gen\b", r"\bcontent\s+marketing\b",
    r"\bsales\s+director\b", r"\bsales\s+manager\b",
    r"\baccount\s+executive\b", r"\baccount\s+manager\b",
    r"\bbusiness\s+development\s+rep\b", r"\bbdr\b", r"\bsdr\b",
    # HR / recruiting / people ops
    r"\brecruiter\b", r"\brecruiting\b", r"\btalent\s+acquisition\b",
    r"\bhuman\s+resources\b", r"\bhr\s+manager\b", r"\bhr\s+director\b",
    r"\bpeople\s+ops\b", r"\bpeople\s+partner\b",
    # Construction / facilities / physical / supply chain
    r"\bconstruction\s+(?:project\s+)?manager\b",
    r"\bfacilities\b", r"\breal\s+estate\s+manager\b",
    r"\bwarehouse\b", r"\bsupply\s+chain\b", r"\blogistics\b",
    r"\bsourcing\b", r"\bprocurement\b", r"\bmanufacturing\b",
    # Medical / clinical / nursing
    r"\bnurse\b", r"\bnursing\b", r"\bclinical\b", r"\bphysician\b",
    r"\bpharmacist\b", r"\bdentist\b", r"\btherapist\b",
    # Executive assistants / admin
    r"\bexecutive\s+assistant\b", r"\badministrative\s+assistant\b",
    r"\boffice\s+manager\b",
]


@lru_cache(maxsize=1)
def _compiled_patterns() -> dict[str, list[re.Pattern]]:
    """Compile all role patterns once, cached."""
    return {
        role: [re.compile(p, re.IGNORECASE) for p in patterns]
        for role, patterns in ROLE_PATTERNS.items()
    }


@lru_cache(maxsize=1)
def _compiled_exclusions() -> list[re.Pattern]:
    """Compile exclusion patterns once, cached."""
    return [re.compile(p, re.IGNORECASE) for p in EXCLUDED_TITLE_PATTERNS]


def _is_excluded(title: str) -> bool:
    """Check if a title matches any exclusion pattern."""
    for pat in _compiled_exclusions():
        if pat.search(title):
            return True
    return False


def classify_role(title: str) -> str | None:
    """Classify a job title into a role category.

    Returns the role key (e.g. "pm", "tpm", "swe") or None if no match.
    Checks exclusion patterns first — a "Construction Project Manager"
    or "Marketing Director" will return None even though it contains
    "project manager" or "marketing".
    """
    if not title:
        return None

    # Exclusion check first — hard reject irrelevant titles
    if _is_excluded(title):
        return None

    compiled = _compiled_patterns()
    for role, patterns in compiled.items():
        for pat in patterns:
            if pat.search(title):
                return role
    return None


def classify_roles_multi(title: str) -> list[str]:
    """Return ALL matching role categories for a title (may match multiple)."""
    if not title:
        return []

    compiled = _compiled_patterns()
    matches = []
    for role, patterns in compiled.items():
        for pat in patterns:
            if pat.search(title):
                matches.append(role)
                break
    return matches


def get_resume_tag_for_role(role: str) -> str:
    """Get the resume tag to use for a given role category."""
    return ROLE_RESUME_MAP.get(role, role)


def is_role_match(title: str, allowed_roles: list[str]) -> bool:
    """Check if a job title matches any of the allowed role categories."""
    role = classify_role(title)
    return role is not None and role in allowed_roles
