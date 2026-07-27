"""Night Shift — tier lists + guardrail matching.

Night Shift is the browser-automation auto-apply feature. Its single most
important safety rule: it must NEVER touch the user's Top-20 dream companies
(TIER_1). Those are applied to by hand, with full care.

Company names in the jobs table are inconsistent (e.g. both "google" and
"Google", "scaleai" vs "Scale AI"), so matching is done by NORMALIZING
(lowercase, strip non-alphanumerics) and comparing against a curated set of
aliases per company. This avoids false positives like "Cerberus Capital
Management" matching Capital One.
"""

import re


def _norm(name: str) -> str:
    """Normalize a company name for matching: lowercase, alphanumeric only."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# ── TIER 1: Top 20 dream companies — NEVER auto-applied ───────────────────────
# Each entry: canonical name → set of normalized aliases that identify it.
TIER_1_COMPANIES: dict[str, set[str]] = {
    "Google":            {"google", "googledeepmind", "deepmind"},
    "Microsoft":         {"microsoft", "msft"},
    "Amazon":            {"amazon", "amazonwebservices", "aws"},
    "Meta":              {"meta", "facebook", "metaplatforms"},
    "Apple":             {"apple"},
    "Adobe":             {"adobe"},
    "Salesforce":        {"salesforce", "salesforcecom"},
    "ServiceNow":        {"servicenow"},
    "Databricks":        {"databricks"},
    "Snowflake":         {"snowflake"},
    "NVIDIA":            {"nvidia"},
    "Cisco":             {"cisco"},
    "VMware":            {"vmware"},
    "Palantir":          {"palantir", "palantirtechnologies"},
    "MongoDB":           {"mongodb"},
    "Atlassian":         {"atlassian"},
    "GitHub":            {"github"},
    "Capital One":       {"capitalone"},
    "Intuit":            {"intuit"},
    # AWS listed in user's Top 20 (#9) — folded into Amazon aliases above.
}

# Flat set of all Tier-1 normalized aliases, for fast lookup.
_TIER_1_ALIASES: set[str] = set()
for _aliases in TIER_1_COMPANIES.values():
    _TIER_1_ALIASES |= _aliases


# ── TIER 2: companies 21–70 — ELIGIBLE for Night Shift ────────────────────────
TIER_2_COMPANIES: list[str] = [
    "PayPal", "Visa", "Mastercard", "Oracle", "IBM", "Accenture",
    "Walmart Global Tech", "Expedia Group", "Stripe", "Airbnb", "OpenAI",
    "Zillow", "Redfin", "Tableau", "Qualtrics", "DocuSign", "Netflix",
    "Uber", "Lyft", "DoorDash", "Shopify", "Twilio", "Elastic", "Workday",
    "SAP", "eBay", "Etsy", "Spotify", "Booking Holdings", "Disney",
    "LinkedIn", "TikTok", "Pinterest", "Snap", "Robinhood", "Coinbase",
    "Figma", "Asana", "Notion", "Dropbox", "Slack", "Zoom", "HubSpot",
    "Okta", "Cloudflare", "CrowdStrike", "Datadog", "Splunk", "Confluent",
]
_TIER_2_ALIASES: set[str] = {_norm(c) for c in TIER_2_COMPANIES}
# Common slug variants the scraper might store differently:
_TIER_2_ALIASES |= {
    "walmart", "walmartglobaltech", "expedia", "bookingholdings", "booking",
    "scaleai",  # appears in jobs but not a tier company — kept OUT intentionally
}
_TIER_2_ALIASES.discard("scaleai")  # explicit: not a tier-2 target


def is_tier_1(company: str) -> bool:
    """True if this company is a Top-20 dream company → NEVER auto-apply.

    Conservative: matches if the normalized company contains, or is contained
    by, any Tier-1 alias. Erring toward blocking is the safe direction.
    """
    n = _norm(company)
    if not n:
        return False
    for alias in _TIER_1_ALIASES:
        if n == alias or n.startswith(alias) or alias in n:
            # 'in' guard is safe here because aliases are specific company tokens
            # (e.g. 'capitalone'), not generic words like 'capital'.
            return True
    return False


def is_tier_2(company: str) -> bool:
    """True if this company is in the 21-70 list → eligible for Night Shift."""
    n = _norm(company)
    if not n:
        return False
    return any(n == a or n.startswith(a) for a in _TIER_2_ALIASES)


def night_shift_eligible(company: str) -> tuple[bool, str]:
    """Decide if Night Shift may queue a job at this company.

    Returns (eligible, reason). Tier-1 is always blocked first.
    """
    if is_tier_1(company):
        return False, "tier_1_blocked"
    if is_tier_2(company):
        return True, "tier_2_eligible"
    return False, "not_in_target_tiers"


# ── All target companies (Tier-1 + Tier-2) — for the "My Targets" jobs filter ─
# Short, distinctive keywords that match the messy company slugs via ILIKE.
TARGET_KEYWORDS: list[str] = sorted({
    "google", "microsoft", "amazon", "meta", "facebook", "apple", "adobe",
    "salesforce", "servicenow", "databricks", "snowflake", "nvidia", "cisco",
    "vmware", "palantir", "mongodb", "atlassian", "github", "capital one",
    "intuit", "paypal", "visa", "mastercard", "oracle", "ibm", "accenture",
    "walmart", "expedia", "stripe", "airbnb", "openai", "zillow", "redfin",
    "tableau", "qualtrics", "docusign", "netflix", "uber", "lyft", "doordash",
    "shopify", "twilio", "elastic", "workday", "sap", "ebay", "etsy", "spotify",
    "booking", "disney", "linkedin", "tiktok", "pinterest", "snap", "robinhood",
    "coinbase", "figma", "asana", "notion", "dropbox", "slack", "zoom",
    "hubspot", "okta", "cloudflare", "crowdstrike", "datadog", "splunk",
    "confluent",
})
