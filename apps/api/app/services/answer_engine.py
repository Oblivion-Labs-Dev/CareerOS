"""JobPilot — Smart answer engine for custom screening questions.

Generates per-company, per-role answers for common ATS questions like:
  - "Why do you want to work at {company}?"
  - "Tell us about yourself"
  - "Years of experience"
  - "Salary expectations"

Two-tier system:
  1. answers.yaml — Your custom answers (highest priority, editable)
  2. Built-in patterns — Company-specific generated answers (fallback)
"""

import re
from pathlib import Path

import yaml

ANSWERS_FILE = Path(__file__).resolve().parents[2] / "data" / "job_discover" / "answers.yaml"

# ── Company context for personalized answers ─────────────────────────────────

COMPANY_CONTEXT = {
    # Big Tech
    "anthropic": {"mission": "AI safety", "what": "building safe, beneficial AI systems", "vibe": "research-driven"},
    "openai": {"mission": "ensuring AGI benefits all of humanity", "what": "pushing the frontier of AI capabilities", "vibe": "research-meets-product"},
    "google": {"mission": "organizing the world's information", "what": "building products that billions of people use daily", "vibe": "engineering excellence"},
    "meta": {"mission": "connecting people and building community", "what": "shaping the future of social connection and the metaverse", "vibe": "move fast"},
    "apple": {"mission": "creating products that enrich people's lives", "what": "designing technology at the intersection of liberal arts and engineering", "vibe": "design-first"},
    "amazon": {"mission": "being Earth's most customer-centric company", "what": "reinventing how the world shops, computes, and entertains", "vibe": "customer obsession"},
    "microsoft": {"mission": "empowering every person and organization to achieve more", "what": "building the cloud and productivity tools that run the world", "vibe": "growth mindset"},

    # Unicorns & Growth
    "stripe": {"mission": "increasing the GDP of the internet", "what": "building financial infrastructure for the internet economy", "vibe": "craft and rigor"},
    "databricks": {"mission": "democratizing data and AI", "what": "unifying data engineering and data science", "vibe": "open-source driven"},
    "datadog": {"mission": "making cloud infrastructure observable", "what": "giving engineering teams clarity into complex distributed systems", "vibe": "engineering-focused"},
    "cloudflare": {"mission": "helping build a better internet", "what": "protecting and accelerating the web for millions of sites", "vibe": "security-first"},
    "figma": {"mission": "making design accessible to everyone", "what": "revolutionizing how teams design and collaborate", "vibe": "creative and collaborative"},
    "discord": {"mission": "creating space for everyone to find belonging", "what": "building the platform where communities thrive", "vibe": "community-driven"},
    "notion": {"mission": "making toolmaking ubiquitous", "what": "empowering teams to build their own workflows", "vibe": "craft and simplicity"},
    "ramp": {"mission": "helping companies spend less", "what": "building the finance automation platform companies actually love", "vibe": "speed and efficiency"},
    "airbnb": {"mission": "creating a world where anyone can belong anywhere", "what": "reimagining how people experience travel", "vibe": "design and belonging"},
    "spotify": {"mission": "unlocking the potential of human creativity", "what": "personalizing how billions experience music and podcasts", "vibe": "data-meets-culture"},
    "coinbase": {"mission": "creating an open financial system for the world", "what": "building the most trusted crypto platform", "vibe": "crypto-native"},
    "doordash": {"mission": "empowering local economies", "what": "connecting people with local businesses through logistics", "vibe": "operator mentality"},
    "uber": {"mission": "reimagining the way the world moves", "what": "building mobility and delivery at massive global scale", "vibe": "bold bets"},
    "salesforce": {"mission": "making business a platform for change", "what": "building the world's leading CRM and enterprise cloud", "vibe": "trust and innovation"},
    "pinterest": {"mission": "bringing everyone the inspiration to create a life they love", "what": "building visual discovery for a more inspired internet", "vibe": "positive and creative"},
    "duolingo": {"mission": "making education free and accessible", "what": "gamifying language learning for hundreds of millions", "vibe": "fun and mission-driven"},
    "reddit": {"mission": "bringing community and belonging to everyone", "what": "building the front page of the internet", "vibe": "authentic and community-first"},
    "instacart": {"mission": "creating a world where everyone has access to food they love", "what": "reinventing grocery delivery with technology", "vibe": "customer-centric"},
    "mongodb": {"mission": "making data easier to work with", "what": "building the developer data platform", "vibe": "developer-first"},
    "snowflake": {"mission": "enabling every organization to be data-driven", "what": "building the data cloud that scales without limits", "vibe": "performance-obsessed"},
    "palantir": {"mission": "building software that empowers institutions to make better decisions", "what": "solving the hardest data integration problems", "vibe": "mission-driven"},
    "gitlab": {"mission": "making it so everyone can contribute", "what": "building the complete DevOps platform in a single application", "vibe": "transparent and remote-first"},
    "okta": {"mission": "enabling any organization to use any technology", "what": "securing digital identity for the modern enterprise", "vibe": "security and trust"},
    "robinhood": {"mission": "democratizing finance for all", "what": "making investing accessible to everyone", "vibe": "disruptive and bold"},
    "plaid": {"mission": "unlocking financial freedom for everyone", "what": "building the infrastructure that connects fintech", "vibe": "API-first"},
    "perplexityai": {"mission": "making knowledge accessible and accurate", "what": "building an AI-powered answer engine that cites its sources", "vibe": "search reimagined"},
    "canva": {"mission": "empowering everyone to design", "what": "democratizing design for non-designers worldwide", "vibe": "accessible and visual"},
    "grammarly": {"mission": "improving lives by improving communication", "what": "building AI that helps people write more effectively", "vibe": "thoughtful and inclusive"},
}

# ── Question detection patterns ──────────────────────────────────────────────

QUESTION_PATTERNS = {
    "why_company": [
        r"why.*(?:want|interested|excited|apply|join|work).*(?:here|us|at\s|company|team|\?)",
        r"what.*(?:interest|attract|excite|draw).*(?:this|our|role|position|company)",
        r"why.*(?:this|our).*(?:role|position|company|team)",
        r"motivation.*(?:apply|join)",
        r"why.*(?:excited|interested).*(?:about|role|this)",
        r"what\s+(?:excites|interests|motivates).*(?:about|this|role)",
    ],
    "about_yourself": [
        r"tell\s+(?:us|me)\s+about\s+yourself",
        r"describe\s+yourself",
        r"brief\s+(?:introduction|summary|bio)",
        r"introduce\s+yourself",
    ],
    "years_experience": [
        r"(?:how\s+many\s+)?years?\s+(?:of\s+)?experience",
        r"total\s+(?:years?|experience)",
    ],
    "salary": [
        r"salary\s+(?:expectation|requirement|range)",
        r"compensation\s+(?:expectation|requirement)",
        r"expected\s+(?:salary|compensation|pay)",
        r"desired\s+(?:salary|compensation|pay)",
    ],
    "start_date": [
        r"(?:earliest|when).*(?:start|available|begin)",
        r"start\s+date",
        r"availability",
        r"notice\s+period",
    ],
    "work_auth": [
        r"(?:legally\s+)?(?:authorized|eligible).*(?:work|employment)",
        r"work\s+(?:authorization|permit|eligibility)",
        r"right\s+to\s+work",
    ],
    "sponsorship": [
        r"(?:require|need).*(?:sponsor|visa)",
        r"(?:sponsor|visa).*(?:require|need)",
        r"immigration.*(?:sponsor|support)",
    ],
    "referral": [
        r"how\s+did\s+you\s+(?:hear|find|learn)",
        r"(?:referred|referral)",
        r"source",
        r"where.*(?:hear|find|learn).*(?:about|this)",
    ],
    "linkedin": [
        r"linkedin",
        r"linked\s*in.*(?:profile|url|link)",
    ],
    "github": [
        r"github",
        r"git\s*hub.*(?:profile|url|link)",
        r"code.*(?:repository|portfolio)",
    ],
    "website": [
        r"(?:personal\s+)?website",
        r"portfolio.*(?:url|link|site)",
        r"(?:personal|online)\s+(?:url|link|site)",
    ],
    "cover_letter": [
        r"cover\s+letter",
        r"letter\s+of\s+(?:interest|motivation|intent)",
        r"why.*(?:good|great|right)\s+(?:fit|candidate|match)",
    ],
}


def load_custom_answers() -> dict:
    """Load user's custom answers from answers.yaml.

    Returns dict mapping lowercase question pattern → answer string.
    """
    if not ANSWERS_FILE.exists():
        return {}
    try:
        raw = yaml.safe_load(ANSWERS_FILE.read_text()) or {}
        # Flatten: {"pattern": {"answer": "value"}} → {"pattern": "value"}
        answers = {}
        for pattern, config in raw.items():
            if isinstance(config, dict):
                answers[pattern.lower().strip()] = config.get("answer", "")
            elif isinstance(config, str):
                answers[pattern.lower().strip()] = config
        return answers
    except Exception:
        return {}


def lookup_custom_answer(question_text: str, company: str = "", profile: dict | None = None) -> str | None:
    """Check if answers.yaml has a match for this question.

    Returns:
        Answer string if found (empty string means "[skip]"),
        None if no custom answer configured.
    """
    custom = load_custom_answers()
    if not custom:
        return None

    lower = question_text.lower().strip()
    for pattern, answer in custom.items():
        if pattern in lower:
            if answer == "[skip]":
                return ""  # Empty = leave blank
            # Substitute variables
            if profile:
                answer = answer.replace("{first_name}", profile.get("first_name", ""))
                answer = answer.replace("{last_name}", profile.get("last_name", ""))
            if company:
                answer = answer.replace("{company}", company.title())
            return answer

    return None  # No custom answer found


def detect_question_type(question_text: str) -> str | None:
    """Detect what type of question is being asked."""
    lower = question_text.lower().strip()
    for qtype, patterns in QUESTION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, lower):
                return qtype
    return None


def _normalize_profile(profile: dict | None) -> dict:
    if not profile:
        return {}
    return {
        **profile,
        "first_name": profile.get("first_name") or profile.get("firstName") or "",
        "last_name": profile.get("last_name") or profile.get("lastName") or "",
        "current_title": profile.get("current_title") or profile.get("currentTitle") or "",
        "current_company": profile.get("current_company") or profile.get("currentCompany") or "",
        "years_experience": profile.get("years_experience") or profile.get("yearsExperience") or 0,
        "work_auth": profile.get("work_auth") or profile.get("workAuthorization") or "Yes",
        "sponsorship": profile.get("sponsorship") or profile.get("needsSponsorship") or "No",
        "linkedin": profile.get("linkedin") or "",
        "github": profile.get("github") or "",
        "website": profile.get("website") or profile.get("portfolio") or profile.get("linkedin") or "",
    }


def generate_answer(
    question_text: str,
    company: str,
    role_title: str,
    profile: dict,
) -> str:
    """Generate a contextual answer for a screening question.

    Priority:
      1. answers.yaml custom answers (user-defined, highest priority)
      2. Built-in pattern matching + company context (auto-generated)

    Args:
        question_text: The question being asked (label text).
        company: Company name (lowercase slug).
        role_title: The job title being applied for.
        profile: User's profile dict from the database.

    Returns:
        Answer string, or empty string if question should be skipped.
    """
    # ── Priority 1: Check answers.yaml ──
    normalized_profile = _normalize_profile(profile)
    custom = lookup_custom_answer(question_text, company, normalized_profile)
    if custom is not None:
        return custom

    # ── Priority 2: Built-in pattern matching ──
    qtype = detect_question_type(question_text)
    if not qtype:
        return ""

    company_lower = company.lower().replace(" ", "").replace("-", "")
    ctx = COMPANY_CONTEXT.get(company_lower, {})
    normalized_profile.get("first_name", "")
    normalized_profile.get("current_title", "")
    normalized_profile.get("current_company", "")
    years = normalized_profile.get("years_experience", 0)

    if qtype == "why_company":
        return _generate_why_company(company, role_title, normalized_profile, ctx)

    elif qtype == "about_yourself":
        return _generate_about(normalized_profile, role_title)

    elif qtype == "years_experience":
        return str(years) if years else ""

    elif qtype == "salary":
        # Never auto-fill salary — user should decide
        return ""

    elif qtype == "start_date":
        return "2 weeks notice - flexible"

    elif qtype == "work_auth":
        return normalized_profile.get("work_auth", "Yes")

    elif qtype == "sponsorship":
        return normalized_profile.get("sponsorship", "No")

    elif qtype == "referral":
        return "Online Job Board"

    elif qtype == "linkedin":
        return normalized_profile.get("linkedin", "")

    elif qtype == "github":
        return normalized_profile.get("github", "")

    elif qtype == "website":
        return normalized_profile.get("website", normalized_profile.get("linkedin", ""))

    elif qtype == "cover_letter":
        default = normalized_profile.get("cover_letter_default", "")
        if default and ctx:
            # Light personalization of the default cover letter
            return default.replace("{company}", company.title()).replace("{role}", role_title)
        return default

    return ""


def _generate_why_company(company: str, role_title: str, profile: dict, ctx: dict) -> str:
    """Generate a 'Why do you want to work here?' answer."""
    profile.get("first_name", "")
    current_title = profile.get("current_title", "")
    years = profile.get("years_experience", 0)
    skills = profile.get("skills", "")

    # If we have company context, generate a personalized answer
    if ctx:
        mission = ctx.get("mission", "")
        what = ctx.get("what", "")

        answer = (
            f"I'm excited about this {role_title} opportunity because "
            f"{company.title()}'s mission of {mission} deeply resonates with me. "
        )

        if current_title:
            answer += (
                f"As a {current_title} with {years}+ years of experience, "
                f"I've developed strong expertise in {skills.split(',')[0].strip() if skills else 'cross-functional collaboration'}. "
            )

        answer += (
            f"I'm drawn to {company.title()} specifically because you're {what}, "
            f"and I believe my background positions me to contribute meaningfully "
            f"to that mission from day one."
        )
        return answer

    # Generic fallback
    answer = f"I'm excited about this {role_title} role at {company.title()}. "
    if current_title:
        answer += f"With {years}+ years of experience as a {current_title}, "
    answer += (
        "I'm looking for an opportunity where I can apply my skills to meaningful "
        "challenges while growing alongside a talented team. I'm particularly drawn "
        "to the impact this role can have and would love to contribute to your mission."
    )
    return answer


def _generate_about(profile: dict, role_title: str) -> str:
    """Generate a 'Tell us about yourself' answer."""
    profile.get("first_name", "")
    current_title = profile.get("current_title", "")
    current_company = profile.get("current_company", "")
    years = profile.get("years_experience", 0)
    skills = profile.get("skills", "")

    parts = []

    if current_title and current_company:
        parts.append(
            f"I'm a {current_title} at {current_company} with {years}+ years of experience."
        )
    elif current_title:
        parts.append(f"I'm a {current_title} with {years}+ years of experience.")

    if skills:
        skill_list = [s.strip() for s in skills.split(",")][:4]
        parts.append(
            f"My core strengths include {', '.join(skill_list[:-1])} and {skill_list[-1]}."
            if len(skill_list) > 1
            else f"I specialize in {skill_list[0]}."
        )

    parts.append(
        f"I'm currently exploring {role_title} opportunities where I can "
        f"drive meaningful impact while continuing to grow professionally."
    )

    return " ".join(parts)


# ── Bulk answer generation for a full application ────────────────────────────

def generate_all_answers(
    questions: list[str],
    company: str,
    role_title: str,
    profile: dict,
) -> dict[str, str]:
    """Generate answers for a list of question texts.

    Returns: dict mapping question_text → answer (empty string = skip)
    """
    results = {}
    for q in questions:
        answer = generate_answer(q, company, role_title, profile)
        results[q] = answer
    return results
