"""Build a job-match profile from a resume with plain code (no model call).

``profile_match.py`` scores every job against a profile: which role families
and levels fit, which skills the candidate has and how strongly. The bundled
profile is neutral, so until someone writes their own JSON every posting is
scored on its own text. This module reads the uploaded resume once and writes
that profile automatically:

* skills come from a catalog of synonym patterns; a skill named on the resume
  counts as "have" (more mentions, more weight), a catalog skill that is
  missing counts as a soft gap (0.2, above the hard-gap threshold, because a
  resume never lists everything someone knows);
* the role family is read from the current title and the resume body, and
  related families get partial credit through ``family_affinity``;
* the level comes from the title, or from years of experience when the title
  says nothing; with neither it stays neutral rather than guessed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.application_assistant.role_shape_match import (
    ROLE_FAMILIES,
    SENIORITY_LEVELS,
    detect_role_family,
    family_affinity,
)

#: Where the generated profile lives (user data, never committed or exported).
GENERATED_PROFILE_PATH = Path(__file__).resolve().parents[3] / "data" / "profile" / "match_profile.json"

#: Below this much text the resume was not really read (scan, empty export).
MIN_RESUME_CHARS = 200
ABSENT_HAVE = 0.2
UNKNOWN_FAMILY_FIT = 0.75

#: name -> (pattern, generic). Generic skills appear in most postings, so the
#: scorer gives them less weight.
SKILL_CATALOG: dict[str, tuple[str, bool]] = {
    # Languages
    "java": (r"\bjava\b(?!\s*script)", False),
    "csharp": (r"c#|\.net\b|dotnet", False),
    "python": (r"\bpython\b", False),
    "cpp": (r"c\+\+", False),
    "typescript": (r"typescript|\bnode(?:\.js|js)?\b|javascript", False),
    "go": (r"\bgolang\b|\bgo\b(?=\s*(?:,|/|\)|$))", False),
    "rust": (r"\brust\b", False),
    "ruby": (r"\bruby\b|\brails\b", False),
    "scala": (r"\bscala\b", False),
    "kotlin": (r"\bkotlin\b", False),
    "php": (r"\bphp\b|laravel", False),
    "swift_ios": (r"\bswift\b|\bios\b|objective.c|swiftui", False),
    "android": (r"\bandroid\b|jetpack compose", False),
    "sql": (r"\bsql\b|postgres|mysql|relational database", True),
    # Web and systems
    "react": (r"\breact\b(?!\s*native)", False),
    "frontend_deep": (r"\bcss\b|design system|accessibility|webpack|\bvue\b|angular|svelte|next\.js", False),
    "distributed": (r"distributed system|high.scale|large.scale|scalab|high.throughput|low.latency", True),
    "microservices": (r"microservice|service.oriented|\bsoa\b", True),
    "api": (r"\brest(?:ful)?\b|\bgrpc\b|graphql|\bapis?\b", True),
    "event_driven": (r"event.driven|kafka|kinesis|\bsqs\b|pub/?sub|message queue|rabbitmq", False),
    "nosql": (r"nosql|dynamodb|cosmos ?db|mongodb|cassandra", False),
    "redis": (r"\bredis\b|caching|memcache", True),
    "linux": (r"\blinux\b|\bunix\b", False),
    # Cloud and operations
    "aws": (r"\baws\b|amazon web services|\bec2\b|\bs3\b|lambda|dynamodb|cloudwatch|sagemaker", False),
    "azure": (r"\bazure\b", False),
    "gcp": (r"\bgcp\b|google cloud|bigquery", False),
    "kubernetes": (r"kubernetes|\bk8s\b|\beks\b|\baks\b|\bgke\b", False),
    "docker": (r"docker|container", True),
    "iac": (r"terraform|infrastructure as code|cloudformation|pulumi", False),
    "cicd": (r"ci/cd|continuous (?:integration|delivery|deployment)|github actions|jenkins", True),
    "observability": (r"observability|monitoring|grafana|prometheus|opentelemetry|datadog|\bslos?\b", True),
    # Data and AI
    "spark_data": (r"\bspark\b|airflow|\bdbt\b|snowflake|databricks|\betl\b|data warehouse", False),
    "ml_classic": (r"machine learning|\bml\b|xgboost|scikit|forecasting|recommendation system", False),
    "deep_learning": (r"pytorch|tensorflow|deep learning|neural net", False),
    "llm": (r"\bllms?\b|large language model|generative ai|\bgenai\b|prompt engineering", False),
    "ai_agents": (r"agentic|ai agents?|model context protocol|langchain|langgraph", False),
    "rag": (r"\brag\b|retrieval.augmented|vector (?:search|database|store)|embeddings|semantic search", False),
    # Security
    "security": (r"security|threat|\bsiem\b|zero trust|vulnerab|incident response", False),
    "auth": (r"oauth|\bsso\b|authentication|authorization|\biam\b", False),
    "test_automation": (r"playwright|selenium|cypress|test automation", False),
    # Product, program and design
    "product_strategy": (r"product strategy|roadmap|go.to.market|product vision|product requirements|\bprds?\b", False),
    "experimentation": (r"a/b test|experimentation|split test", False),
    "product_analytics": (r"tableau|looker|amplitude|mixpanel|power ?bi|product analytics", False),
    "agile": (r"\bagile\b|\bscrum\b|kanban|\bjira\b", True),
    "stakeholders": (r"stakeholder|cross.functional", True),
    "program_management": (r"program management|\bpmp\b|risk management|release management|dependency management", False),
    "ux_research": (r"user research|ux research|usability|figma|wireframe|prototyp", False),
    "excel": (r"\bexcel\b|spreadsheet", True),
}

#: Industries a resume can show; a posting in one of them gets a small boost.
DOMAIN_CATALOG: dict[str, str] = {
    "security": r"security|threat|detection|data protection|zero trust|identity",
    "ai": r"agentic|ai agents?|\bllms?\b|generative ai|\bgenai\b|machine learning",
    "developer_platform": r"developer platform|developer experience|internal platform|developer tools|devtools",
    "commerce": r"e-?commerce|fulfillment|inventory|supply chain|retail|marketplace",
    "cloud": r"cloud platform|cloud infrastructure|cloud.native|multi.cloud",
    "fintech": r"fintech|payments?|banking|trading|lending|insurance",
    "healthcare": r"healthcare|health care|clinical|\behr\b|hipaa|patient",
    "ads": r"advertising|ad tech|adtech|ads platform",
    "gaming": r"\bgaming\b|game studio|video games?",
    "education": r"edtech|education|learning platform",
}

NEUTRAL_SENIORITY_FIT = {"0": 0.75, "1": 0.85, "2": 1.0, "3": 1.0, "4": 0.9, "5": 0.75}
CLEARANCE_RE = (
    r"security clearance|ts/sci|top secret|secret clearance|active clearance|polygraph"
    r"|clearance (?:is )?required"
)


def _have_from_mentions(count: int) -> float:
    if count <= 0:
        return ABSENT_HAVE
    return {1: 0.7, 2: 0.85}.get(count, 1.0)


def _parse_years(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 0 else None
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else None


def _title_level(title: str) -> int | None:
    """The level a title states, or None when it states none."""
    for pattern, level in SENIORITY_LEVELS:
        if re.search(pattern, title, re.I):
            return level
    return None


def _years_level(years: int) -> int:
    if years < 1:
        return 0
    if years < 3:
        return 1
    if years < 6:
        return 2
    if years < 10:
        return 3
    return 4


def _seniority_fit(level: int) -> dict[str, float]:
    taper = {0: 1.0, 1: 0.9, -1: 0.8, 2: 0.5, -2: 0.45}
    return {str(n): taper.get(n - level, 0.25) for n in range(6)}


#: A plain "Software Engineer" title names no family, but fits these.
GENERALIST_TITLE = re.compile(r"software|developer|\bswe\b|\bsde\b|engineer", re.I)
GENERALIST_FAMILIES = ("backend", "fullstack")
#: A resume can fit several families; those within this share of the best count.
FAMILY_SHARE = 0.5
MIN_FAMILY_SIGNAL = 0.25


def _family_fit(title: str, text: str) -> tuple[str, dict[str, float]]:
    """Primary family plus a fit for every family.

    Postings name one family; resumes describe several kinds of work, and
    their cues are weaker than a posting's, so every family close to the best
    one counts and the rest get credit through ``family_affinity``.
    """
    _best, scores = detect_role_family(title, text)
    top = max(scores.values(), default=0.0)
    fits = [f for f, s in scores.items() if top >= MIN_FAMILY_SIGNAL and s >= FAMILY_SHARE * top]
    title_named = any(re.search(c, title.lower()) for cues in ROLE_FAMILIES.values() for c in cues["title"])
    if not title_named and GENERALIST_TITLE.search(title):
        fits += [f for f in GENERALIST_FAMILIES if f not in fits]
    if not fits:
        return "", {"": UNKNOWN_FAMILY_FIT}
    family = max(fits, key=lambda f: scores.get(f, 0.0))
    fit = {f: round(max(family_affinity(g, f) for g in fits), 2) for f in ROLE_FAMILIES}
    fit[""] = UNKNOWN_FAMILY_FIT
    return family, fit


def build_match_profile(resume_text: str, *, title: str = "", years: Any = None,
                        resume_file: str = "") -> dict[str, Any]:
    """Return a ``resume_match_profile.json``-shaped dict for this resume.

    Raises ValueError when the text is too short to have been read properly,
    so a failed extraction never silently becomes "this person has no skills".
    """
    text = (resume_text or "").strip()
    if len(text) < MIN_RESUME_CHARS:
        raise ValueError(
            f"Resume text is too short to build a match profile ({len(text)} characters); "
            "the file may be a scan or empty."
        )
    title = (title or "").strip()
    years_n = _parse_years(years)

    skills: dict[str, dict[str, Any]] = {}
    for name, (pattern, generic) in SKILL_CATALOG.items():
        count = len(re.findall(pattern, text, re.I | re.M))
        entry: dict[str, Any] = {"re": pattern, "have": _have_from_mentions(count)}
        if generic:
            entry["generic"] = True
        skills[name] = entry

    domains = {name: pattern for name, pattern in DOMAIN_CATALOG.items() if re.search(pattern, text, re.I)}
    family, family_fit = _family_fit(title, text)

    level = _title_level(title) if title else None
    if level is None and years_n is not None:
        level = _years_level(years_n)
    seniority_fit = _seniority_fit(level) if level is not None else dict(NEUTRAL_SENIORITY_FIT)

    return {
        "_about": (
            "Generated by match_profile_builder.py from the uploaded resume with plain code, "
            f"on {datetime.now(timezone.utc).date().isoformat()}. It is rewritten each time the "
            "resume is parsed; point CAREEROS_MATCH_PROFILE at your own file to tune it by hand."
        ),
        "generated": True,
        "resume_file": resume_file,
        "years_experience": years_n,
        "seniority": level,
        "role_family": family,
        "family_fit": family_fit,
        "seniority_fit": seniority_fit,
        "skills": skills,
        "domains": domains,
        "penalties": {
            "years_over": years_n + 4 if years_n is not None else 99,
            "years_penalty": 0.12 if years_n is not None else 0.0,
            "clearance_re": CLEARANCE_RE,
            "clearance_penalty": 0.0,
            "cap": 15,
            "years_cap": 12 if years_n is not None else 99,
            "language_re": "",
        },
    }


def write_match_profile(resume_text: str, *, title: str = "", years: Any = None,
                        resume_file: str = "", path: Path | None = None) -> Path:
    """Build the profile, write it atomically and make the scorer reload it."""
    from app.services.application_assistant.profile_match import default_profile

    target = path or GENERATED_PROFILE_PATH
    profile = build_match_profile(resume_text, title=title, years=years, resume_file=resume_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    default_profile.cache_clear()
    return target
