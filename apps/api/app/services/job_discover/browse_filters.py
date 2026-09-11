"""Browse-only facets. Never change application answers or resume selection."""
import json
import re

from app.services.job_discover.role_classifier import ROLE_LABELS, ROLE_PATTERNS

EXTRA_PATTERNS = {
    "bie": [r"\b(?:business intelligence|bi)\s+(?:engineer|developer|analyst)\b", r"\bbie\b"],
    "data": [r"\bdata\s+(?:analyst|scientist|engineer)\b", r"\banalytics\s+engineer\b"],
    "backend": [r"\bback[ -]?end\b"], "frontend": [r"\bfront[ -]?end\b"],
    "platform": [r"\b(?:platform|infrastructure|devops|site reliability|sre)\b"],
    "ml": [r"\b(?:machine learning|artificial intelligence|ml|ai)\b"],
}
LABELS = {**ROLE_LABELS, "bie": "Business Intelligence / BIE", "data": "Data & Analytics",
          "backend": "Backend", "frontend": "Frontend", "platform": "Platform / Infrastructure", "ml": "AI / ML"}
TITLE_SEEDS = ["Software Engineer", "Product Manager", "Technical Program Manager", "Business Intelligence Engineer", "BIE",
               "Product Analyst", "UX Designer", "Product Designer", "Data Scientist", "Data Analyst", "Data Engineer",
               "Solutions Engineer", "Hardware Engineer", "Backend Engineer", "Frontend Engineer", "Platform Engineer",
               "Machine Learning Engineer", "Site Reliability Engineer", "QA Engineer", "Security Engineer"]


def split_values(value):
    return {part.strip().lower() for part in value.split(",") if part.strip()}


def title_matches(title, roles):
    patterns = {**ROLE_PATTERNS, **EXTRA_PATTERNS}
    return any(re.search(pattern, title, re.I) for role in roles for pattern in patterns.get(role, []))


def seniority_for(title):
    for key, pattern in [("principal", r"\b(principal|distinguished)\b"), ("staff", r"\bstaff\b"),
                         ("lead", r"\b(lead|director|head|manager)\b"), ("senior", r"\b(senior|sr\.?)\b"),
                         ("entry", r"\b(junior|jr\.?|intern|entry|graduate|associate)\b"), ("mid", r"\b(mid|intermediate|ii)\b")]:
        if re.search(pattern, title, re.I):
            # Product/program manager is a job family, not necessarily people leadership.
            if key == "lead" and re.search(r"\b(product|program|project) manager\b", title, re.I) and not re.search(r"\b(lead|director|head)\b", title, re.I):
                continue
            return key
    return "unspecified"


def work_mode_for(job):
    text = str(job.get("workplaceType") or job.get("workMode") or job.get("location") or "").lower()
    if "hybrid" in text:
        return "hybrid"
    if "remote" in text or job.get("remote") is True:
        return "remote"
    if re.search(r"on[ -]?site|in[ -]?office", text):
        return "onsite"
    return "unspecified"


def minimum_experience(job):
    value = job.get("minYearsExperience")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 60:
        return value
    text = re.sub(r"<[^>]+>", " ", str(job.get("description") or ""))
    match = re.search(r"\b(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s*\+?\s+years?(?:\s+of)?\s+(?:(?:relevant|professional|work)\s+)?experience\b", text, re.I)
    return int(match[1]) if match else None


def filter_facets(jobs, *, specialties="", seniorities="", work_modes="", experience="", companies=""):
    roles, levels, modes = map(split_values, [specialties, seniorities, work_modes])
    try:
        employers = {str(value).lower() for value in json.loads(companies)} if companies.startswith("[") else split_values(companies)
    except (ValueError, TypeError):
        employers = set()
    bands = {"0-2": (0, 2), "3-5": (3, 5), "6-9": (6, 9), "10+": (10, 60)}
    def matches(job):
        if roles and not title_matches(str(job.get("title") or ""), roles):
            return False
        if levels and seniority_for(str(job.get("title") or "")) not in levels:
            return False
        if modes and work_mode_for(job) not in modes:
            return False
        if employers and str(job.get("companyName") or "").lower() not in employers:
            return False
        if experience in bands:
            value = minimum_experience(job)
            low, high = bands[experience]
            if value is None or not low <= value <= high:
                return False
        if experience == "unspecified" and minimum_experience(job) is not None:
            return False
        return True
    return [job for job in jobs if matches(job)]


def filter_options(jobs):
    titles = sorted(set(TITLE_SEEDS) | {j["title"] for j in jobs if isinstance(j.get("title"), str) and j["title"].strip()}, key=str.casefold)
    companies = sorted({j["companyName"] for j in jobs if j.get("companyName")}, key=str.casefold)
    return {"titles": titles, "companies": companies, "specialties": [{"value": key, "label": label} for key, label in LABELS.items()]}
