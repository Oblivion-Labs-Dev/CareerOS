"""JobPilot — Relevancy scoring, keyword extraction, recruiter finder, outreach messages.

Scores each job against the user's profile to produce:
  - relevancy_score (0-100%)
  - keywords_matched (list of matching skills/terms)
  - recruiter_url (LinkedIn People Search link)
  - outreach_message (personalized LinkedIn message draft)
"""

import re
from urllib.parse import quote_plus

# ── Relevancy Scoring ───────────────────────────────────────────────────────

# Target role families — maps user's current_title to related role patterns
ROLE_FAMILIES = {
    "product manager": [
        r"\bproduct\s+manager\b", r"\bpm\b", r"\bassociate\s+product\s+manager\b",
        r"\btechnical\s+product\s+manager\b", r"\bsenior\s+product\s+manager\b",
        r"\bgroup\s+product\s+manager\b", r"\bproduct\s+lead\b",
        r"\bproduct\s+owner\b", r"\bhead\s+of\s+product\b",
    ],
    "program manager": [
        r"\bprogram\s+manager\b", r"\btechnical\s+program\s+manager\b",
        r"\btpm\b", r"\bagile\s+program\s+manager\b",
    ],
    "software engineer": [
        r"\bsoftware\s+engineer\b", r"\bswe\b", r"\bsde\b",
        r"\bfrontend\s+engineer\b", r"\bbackend\s+engineer\b",
        r"\bfull[\s-]?stack\s+engineer\b", r"\bplatform\s+engineer\b",
        r"\bsoftware\s+developer\b",
    ],
    "ux designer": [
        r"\bux\s+designer\b", r"\bproduct\s+designer\b", r"\bux\s+researcher\b",
        r"\buser\s+experience\b", r"\bui/ux\b", r"\bux/ui\b",
        r"\binteraction\s+designer\b",
    ],
    "solutions engineer": [
        r"\bsolutions\s+engineer\b", r"\bsales\s+engineer\b",
        r"\bsolutions\s+architect\b", r"\bpre[\s-]?sales\b",
        r"\bsolutions\s+consultant\b",
    ],
    "data scientist": [
        r"\bdata\s+scientist\b", r"\bmachine\s+learning\s+engineer\b",
        r"\bml\s+engineer\b", r"\bai\s+engineer\b", r"\bdata\s+analyst\b",
    ],
}

# Common tech skills to look for in descriptions
SKILL_ALIASES = {
    "python": [r"\bpython\b"],
    "javascript": [r"\bjavascript\b", r"\bjs\b", r"\btypescript\b", r"\bts\b"],
    "react": [r"\breact\b", r"\breact\.js\b", r"\breactjs\b"],
    "sql": [r"\bsql\b", r"\bpostgresql\b", r"\bmysql\b"],
    "aws": [r"\baws\b", r"\bamazon\s+web\s+services\b"],
    "gcp": [r"\bgcp\b", r"\bgoogle\s+cloud\b"],
    "azure": [r"\bazure\b"],
    "docker": [r"\bdocker\b", r"\bkubernetes\b", r"\bk8s\b"],
    "machine learning": [r"\bmachine\s+learning\b", r"\bml\b", r"\bdeep\s+learning\b"],
    "agile": [r"\bagile\b", r"\bscrum\b", r"\bkanban\b"],
    "product management": [r"\bproduct\s+management\b", r"\broadmap\b", r"\bprds?\b"],
    "data analysis": [r"\bdata\s+analysis\b", r"\banalytics\b", r"\btableau\b"],
    "figma": [r"\bfigma\b", r"\bsketch\b"],
    "java": [r"\bjava\b(?!script)"],
    "c++": [r"\bc\+\+\b", r"\bcpp\b"],
    "go": [r"\bgolang\b", r"\bgo\b(?:\s+lang)"],
    "rust": [r"\brust\b"],
    "node": [r"\bnode\.?js\b", r"\bnode\b"],
    "api": [r"\bapi\b", r"\brest\b", r"\bgraphql\b"],
    "ci/cd": [r"\bci/?cd\b", r"\bjenkins\b", r"\bgithub\s+actions\b"],
    "communication": [r"\bcommunication\b", r"\bstakeholder\b", r"\bcross[\s-]?functional\b"],
    "leadership": [r"\bleadership\b", r"\bmentor\b", r"\blead\b"],
    "strategy": [r"\bstrategy\b", r"\bstrategic\b", r"\bvision\b"],
    "a/b testing": [r"\ba/b\s+test\b", r"\bexperiment\b"],
    "user research": [r"\buser\s+research\b", r"\busability\b", r"\buser\s+interview\b"],
}

# Seniority patterns in job titles
SENIORITY_MAP = {
    "intern":     (0, 0),
    "entry":      (0, 2),
    "junior":     (0, 2),
    "associate":  (1, 3),
    "mid":        (2, 6),
    "senior":     (5, 15),
    "staff":      (7, 20),
    "principal":  (10, 25),
    "lead":       (5, 15),
    "manager":    (4, 15),
    "director":   (8, 25),
    "vp":         (12, 30),
    "head":       (8, 25),
}


def _detect_seniority(title: str) -> tuple[int, int]:
    """Return (min_years, max_years) expected for the seniority level in title."""
    t = title.lower()
    for keyword, (lo, hi) in SENIORITY_MAP.items():
        if re.search(rf"\b{re.escape(keyword)}\b", t):
            return (lo, hi)
    return (0, 99)  # Can't tell → matches anyone


def _find_role_family(user_title: str) -> list[re.Pattern]:
    """Find the best-matching role family for the user's title."""
    t = user_title.lower()
    for family_name, patterns in ROLE_FAMILIES.items():
        for p in patterns:
            if re.search(p, t, re.IGNORECASE):
                return [re.compile(pat, re.IGNORECASE) for pat in patterns]
    # No match — return empty (will score 0 for title match)
    return []


def score_job(job: dict, profile: dict) -> dict:
    """Score a job's relevancy to the user's profile.

    Returns:
        {
            "relevancy_score": int (0-100),
            "keywords_matched": list[str],
            "color": "green" | "yellow" | "orange" | "gray",
        }
    """
    title = job.get("title", "")
    description = (job.get("description", "") or "").lower()
    location = job.get("location", "")
    dept = job.get("department", "")

    user_title = profile.get("current_title", "")
    user_skills_raw = profile.get("skills", "")
    user_years = int(profile.get("years_experience", 0) or 0)
    user_city = profile.get("city", "")
    user_state = profile.get("state", "")

    score = 0
    keywords = []
    full_text = f"{title} {description} {dept}".lower()

    # ── 1. Title match (0-40 pts) ──────────────────────────────────────────
    role_patterns = _find_role_family(user_title)
    title_score = 0
    if role_patterns:
        for pat in role_patterns:
            if pat.search(title):
                title_score = 40
                break
        if title_score == 0:
            # Check if any pattern matches in the description
            for pat in role_patterns:
                if pat.search(description):
                    title_score = 15
                    break
    else:
        # No role family found — try basic keyword overlap between user title and job title
        user_words = set(user_title.lower().split())
        job_words = set(title.lower().split())
        overlap = user_words & job_words - {"the", "a", "an", "and", "or", "at", "in", "for", "-", "/"}
        if overlap:
            title_score = min(30, len(overlap) * 15)
    score += title_score

    # ── 2. Skills match (0-35 pts) ─────────────────────────────────────────
    user_skills = [s.strip().lower() for s in user_skills_raw.split(",") if s.strip()]
    matched_skills = []

    if user_skills:
        for skill in user_skills:
            # Direct match
            if skill in full_text:
                matched_skills.append(skill)
                continue
            # Alias match
            aliases = SKILL_ALIASES.get(skill, [])
            for alias_pat in aliases:
                if re.search(alias_pat, full_text, re.IGNORECASE):
                    matched_skills.append(skill)
                    break

        if user_skills:
            skills_ratio = len(matched_skills) / len(user_skills)
            score += round(35 * skills_ratio)
    keywords.extend(matched_skills)

    # Also find skills from SKILL_ALIASES that appear in the job but user doesn't have
    # (these are "bonus" keywords for display)
    for skill_name, patterns in SKILL_ALIASES.items():
        if skill_name not in matched_skills:
            for pat in patterns:
                if re.search(pat, full_text, re.IGNORECASE):
                    keywords.append(f"+{skill_name}")  # prefix with + to indicate "nice to have"
                    break

    # ── 3. Experience level match (0-10 pts) ───────────────────────────────
    seniority_min, seniority_max = _detect_seniority(title)
    if seniority_min <= user_years <= seniority_max:
        score += 10
    elif abs(user_years - seniority_min) <= 2 or abs(user_years - seniority_max) <= 2:
        score += 5  # Close enough

    # ── 4. Location preference (0-15 pts) ──────────────────────────────────
    loc_lower = location.lower()
    if user_city and user_city.lower() in loc_lower:
        score += 15
    elif user_state and user_state.lower() in loc_lower:
        score += 10
    elif re.search(r"\bremote\b", loc_lower):
        score += 12
    else:
        score += 3  # Still US, just not local

    # ── Finalize ───────────────────────────────────────────────────────────
    score = min(100, score)

    if score >= 75:
        color = "green"
    elif score >= 50:
        color = "yellow"
    elif score >= 30:
        color = "orange"
    else:
        color = "gray"

    # Deduplicate and clean keywords
    seen = set()
    unique_kw = []
    for kw in keywords:
        kw_clean = kw.lstrip("+")
        if kw_clean not in seen:
            seen.add(kw_clean)
            unique_kw.append(kw)

    return {
        "relevancy_score": score,
        "keywords_matched": unique_kw[:12],  # Cap at 12 keywords
        "color": color,
    }


def score_jobs_batch(jobs: list[dict], profile: dict) -> list[dict]:
    """Score a batch of jobs. Returns jobs with scoring fields injected."""
    for job in jobs:
        result = score_job(job, profile)
        job["relevancy_score"] = result["relevancy_score"]
        job["keywords_matched"] = result["keywords_matched"]
        job["color"] = result["color"]
    return jobs


# ── Recruiter / Hiring Manager Finder ───────────────────────────────────────

def get_recruiter_urls(company: str, role_title: str = "", department: str = "") -> dict:
    """Build LinkedIn People Search URLs to find recruiters and hiring managers.

    Returns dict with different search angles:
      - recruiter_url: search for recruiters at the company
      - hiring_manager_url: search for possible hiring manager
      - team_url: search for team members in the department
    """
    company_clean = company.strip().title()

    recruiter_url = (
        "https://www.linkedin.com/search/results/people/"
        f"?keywords={quote_plus(f'recruiter {company_clean}')}"
        "&origin=GLOBAL_SEARCH_HEADER"
    )

    # Extract core role keyword for hiring manager search
    # "Senior Product Manager, Payments" → "product manager"
    role_core = re.sub(
        r"\b(senior|junior|lead|staff|principal|associate|entry|head|director|vp|intern)\b",
        "", role_title, flags=re.IGNORECASE,
    ).strip(" ,.-/")

    hiring_manager_url = (
        "https://www.linkedin.com/search/results/people/"
        f"?keywords={quote_plus(f'{role_core} manager {company_clean}')}"
        "&origin=GLOBAL_SEARCH_HEADER"
    )

    team_url = ""
    if department:
        team_url = (
            "https://www.linkedin.com/search/results/people/"
            f"?keywords={quote_plus(f'{department} {company_clean}')}"
            "&origin=GLOBAL_SEARCH_HEADER"
        )

    return {
        "recruiter_url": recruiter_url,
        "hiring_manager_url": hiring_manager_url,
        "team_url": team_url,
    }


# ── Personalized Outreach Message Generator ─────────────────────────────────

# Company context (mission snippets for personalization)
COMPANY_CONTEXT = {
    "stripe": "building financial infrastructure for the internet",
    "airbnb": "creating a world where anyone can belong anywhere",
    "meta": "building the future of social connection and the metaverse",
    "google": "organizing the world's information and making it accessible",
    "apple": "creating innovative products that enrich people's lives",
    "amazon": "being Earth's most customer-centric company",
    "microsoft": "empowering every person and organization to achieve more",
    "netflix": "entertaining the world with great stories",
    "spotify": "unlocking the potential of human creativity",
    "salesforce": "helping companies connect with customers in new ways",
    "slack": "making work life simpler and more productive",
    "figma": "making design accessible to everyone who builds products",
    "notion": "building tools that blend into the way people think and create",
    "datadog": "bringing observability to modern cloud infrastructure",
    "snowflake": "mobilizing the world's data with cloud data solutions",
    "databricks": "democratizing data and AI for every organization",
    "vercel": "enabling developers to build a faster web",
    "plaid": "building the infrastructure for fintech applications",
    "coinbase": "building an open financial system for the world",
    "robinhood": "democratizing finance for all",
    "square": "making commerce easy for sellers of all sizes",
    "twilio": "building the communication platform of the future",
    "okta": "enabling secure identity for every person and organization",
    "cloudflare": "helping build a better internet",
    "airtable": "democratizing software creation with no-code tools",
}


def generate_outreach_message(
    profile: dict,
    job: dict,
    contact_name: str = "[Name]",
) -> str:
    """Generate a personalized LinkedIn outreach message.

    Args:
        profile: User's profile dict from DB
        job: Job dict with title, company, etc.
        contact_name: Name of the person to address

    Returns:
        A short, professional outreach message.
    """
    first_name = profile.get("first_name", "")
    last_name = profile.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip() or "a job seeker"
    user_title = profile.get("current_title", "")
    user_company = profile.get("current_company", "")
    user_skills = profile.get("skills", "")
    years = profile.get("years_experience", 0)

    company = job.get("company", "").strip()
    role_title = job.get("title", "").strip()
    department = job.get("department", "")

    # Company-specific hook
    company_key = company.lower().replace(" ", "")
    mission = COMPANY_CONTEXT.get(company_key, "")
    company_line = ""
    if mission:
        company_line = f"I'm particularly drawn to {company}'s mission of {mission}. "

    # Background line
    background = ""
    if user_title and user_company:
        background = f"I'm currently a {user_title} at {user_company}"
        if years:
            background += f" with {years} years of experience"
        background += ". "
    elif user_title:
        background = f"I'm a {user_title}"
        if years:
            background += f" with {years} years of experience"
        background += ". "

    # Top skills highlight (pick first 3)
    skills_list = [s.strip() for s in user_skills.split(",") if s.strip()][:3]
    skills_line = ""
    if skills_list:
        skills_line = f"My expertise in {', '.join(skills_list)} aligns well with what you're looking for. "

    message = (
        f"Hi {contact_name},\n\n"
        f"I came across the {role_title} role at {company} and I'm very interested. "
        f"{background}"
        f"{company_line}"
        f"{skills_line}"
        f"\n\n"
        f"I'd love to learn more about the team and how I could contribute. "
        f"Would you be open to a quick chat?\n\n"
        f"Best regards,\n"
        f"{full_name}"
    )

    return message


# ── Freshness Helper ────────────────────────────────────────────────────────

def compute_freshness(posted_at: str) -> dict:
    """Compute how fresh a job posting is.

    Returns:
        {"hours_ago": int, "label": str, "badge_color": str}
    """
    if not posted_at:
        return {"hours_ago": 999, "label": "Unknown", "badge_color": "gray"}

    from datetime import datetime, timezone

    dt = None

    # Try ISO 8601 first (most common)
    try:
        dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        pass

    # Fallback: fuzzy parse ("May 21, 2026", "21/05/2026", etc.)
    if dt is None:
        try:
            from dateutil import parser as dateparser
            dt = dateparser.parse(posted_at, fuzzy=True)
        except Exception:
            pass

    if dt is None:
        return {"hours_ago": 999, "label": "Unknown", "badge_color": "gray"}

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    hours = (now - dt).total_seconds() / 3600

    if hours < 0:
        hours = 0

    if hours < 24:
        return {"hours_ago": int(hours), "label": f"{int(hours)}h ago", "badge_color": "red"}
    elif hours < 48:
        return {"hours_ago": int(hours), "label": "1d ago", "badge_color": "orange"}
    elif hours < 168:
        days = int(hours / 24)
        return {"hours_ago": int(hours), "label": f"{days}d ago", "badge_color": "yellow"}
    else:
        days = int(hours / 24)
        return {"hours_ago": int(hours), "label": f"{days}d ago", "badge_color": "gray"}
