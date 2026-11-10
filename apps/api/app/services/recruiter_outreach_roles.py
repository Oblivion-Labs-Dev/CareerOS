"""Tailor recruiter outreach emails to the company's currently open roles.

Plain code, no model calls: open roles come from the scraped ``aa_discovered_job``
entities (or, for companies missing there, the company's public Greenhouse, Lever
or Ashby board), each role is ranked against the resume with ``profile_match``,
and the top three recent fits are written into the email: subject, opening, a
short list of the roles with the skills each shares with the resume, the ask, and
the order of the resume highlights. The company's mission line is quoted from its
own postings when one is found. A company with no open role that fits keeps its
original email untouched and is reported as unmatched, so nothing is invented.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from app.services.application_assistant.profile_match import profile_match

DEFAULT_MIN_SCORE = 60.0
DEFAULT_MAX_AGE_DAYS = 30
TOP_ROLES = 3

SKILL_LABELS = {
    "java": "Java", "csharp": "C#", "python": "Python", "cpp": "C++", "typescript": "TypeScript",
    "react": "React", "sql": "SQL", "kql": "Kusto", "distributed": "distributed systems",
    "microservices": "microservices", "api": "API design", "event_driven": "event-driven systems",
    "aws": "AWS", "azure": "Azure", "gcp": "GCP", "kubernetes": "Kubernetes", "docker": "Docker",
    "iac": "infrastructure as code", "cicd": "CI/CD", "nosql": "NoSQL data stores", "redis": "Redis",
    "observability": "observability", "llm": "LLMs", "agents": "AI agents", "rag": "RAG",
    "llm_eval": "LLM evaluation", "security": "security", "auth": "identity and auth",
    "compliance_gov": "compliance", "go": "Go", "linux": "Linux",
}

# Resume highlights, each tagged with the matcher skills/domains it speaks to.
# The text matches the bullets already used in the outreach templates.
HIGHLIGHTS: list[tuple[str, frozenset[str]]] = [
    ("Built enterprise security capabilities protecting more than 237K AI agents across 13K+ tenants.",
     frozenset({"security", "auth", "agents", "ai_agents", "llm", "llm_eval", "compliance_gov"})),
    ("Designed distributed systems handling over 100K transactions per second.",
     frozenset({"distributed", "microservices", "event_driven", "nosql", "redis", "api",
                "commerce_fulfillment", "java", "sql"})),
    ("Built internal tooling that reduced service setup from weeks to hours.",
     frozenset({"developer_platform", "cicd", "kubernetes", "docker", "iac", "observability"})),
    ("Led infrastructure improvements that reduced operational costs by more than $250K per month.",
     frozenset({"cloud", "aws", "azure", "gcp", "iac", "observability", "linux"})),
]
_BULLET_RE = re.compile(r"^\s*•\s*(.+?)\s*$")

LiveLookup = Callable[[str, str], list[dict[str, Any]]]


@dataclass(frozen=True)
class OpenRole:
    company: str
    title: str
    url: str
    score: float
    have: tuple[str, ...]
    domains: tuple[str, ...]
    posted: str


def normalize_company(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def clean_title(title: str) -> str:
    title = (title or "").replace("�", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", title).strip()


def load_open_jobs(db_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Active scraped jobs grouped by normalized company. Fails loudly if the DB is missing."""
    if not db_path.exists():
        raise FileNotFoundError(f"Jobs database not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT payload FROM entities WHERE entity_type = 'aa_discovered_job'"
        ).fetchall()
    finally:
        conn.close()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (payload,) in rows:
        job = json.loads(payload)
        if str(job.get("active")).lower() != "true":
            continue
        grouped[normalize_company(job.get("company") or "")].append(job)
    return grouped


def parse_posted(value: Any) -> date | None:
    """Posting date from the formats the scrapers store (ISO, epoch ms, "September 9, 2026"); None if unknown."""
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, UTC).date()
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return parse_posted(int(text))
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(re.sub(r"\s+", " ", text), "%B %d, %Y").date()
    except ValueError:
        return None


def rank_roles(
    jobs: Iterable[dict[str, Any]],
    min_score: float = DEFAULT_MIN_SCORE,
    max_age_days: int | None = None,
    today: date | None = None,
) -> list[OpenRole]:
    """Fitting roles, best first. Blocked roles, duplicate titles and (when
    ``max_age_days`` is set) postings with a known date older than that are dropped.
    Postings with no known date are kept; they sort after dated ones of equal score."""
    cutoff = (today or datetime.now(UTC).date()) - timedelta(days=max_age_days) if max_age_days else None
    best: dict[str, OpenRole] = {}
    for job in jobs:
        posted = parse_posted(job.get("datePosted")) or parse_posted(job.get("dateDiscovered"))
        if cutoff and posted and posted < cutoff:
            continue
        match = profile_match(job)
        parts = match["matchComponents"]
        if parts["blockers"] or match["matchScore"] < min_score:
            continue
        title = clean_title(job.get("title") or "")
        if not title:
            continue
        role = OpenRole(
            company=str(job.get("company") or ""),
            title=title,
            url=str(job.get("listingUrl") or job.get("applicationUrl") or ""),
            score=float(match["matchScore"]),
            have=tuple(parts["have"]),
            domains=tuple(parts["domains"]),
            posted=posted.isoformat() if posted else "",
        )
        key = title.lower()
        current = best.get(key)
        if current is None or (role.score, role.posted) > (current.score, current.posted):
            best[key] = role
    return sorted(best.values(), key=lambda r: (r.score, r.posted), reverse=True)


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s*(?=[A-Z])|\n+")
# Company-level mission clause: "our mission is to ...", "Airbnb's mission to ...",
# "a mission-driven company dedicated to ...". Team missions ("the team's mission") don't count.
_MISSION_CLAUSE_RE = re.compile(
    r"\b(?:our|its|[A-Z][\w&]*(?:'s|’s))\s+mission\s+(?:is\s+)?(to\s+[^.;:!?]+)"
    r"|\bmission-driven company dedicated to\s+(?:helping\s+)?([^.;:!?]+)")
_CLAUSE_END_RE = re.compile(r",|\s(?:shapes|guides|drives|informs|means|and we|which)\b")
_NOT_COMPANY_LEVEL_RE = re.compile(
    r"equal opportunity|accommodation|benefit|recruit|candidate|divers|inclusi|\byou\b|\byour\b", re.I)


def _clean_text(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"(?<=[A-Za-z])\ufffd(?=[a-z])", "'", text).replace("\ufffd", "")
    return re.sub(r"[™®]", "", text)


def extract_mission(jobs: Iterable[dict[str, Any]], company: str = "") -> str | None:
    """A phrase for "What draws me to <company> is ...", in the company's own words.

    Prefers the company-level mission clause ("its mission to empower local
    economies"), then the company's one-line self-description from its "About us"
    ("the work itself: Samsara is the pioneer of the Connected Operations Cloud").
    The candidate found in the most postings wins. None when no posting has one, so
    the email keeps its original line instead of an invented one.
    """
    missions: dict[str, set[int]] = defaultdict(set)
    about: dict[str, set[int]] = defaultdict(set)
    name = re.escape(company.strip()) if company.strip() else None
    for i, job in enumerate(jobs):
        for raw in _SENTENCE_SPLIT_RE.split(_clean_text(str(job.get("description") or ""))):
            sentence = re.sub(r"\s+", " ", raw).strip(" -•*\t")
            if _NOT_COMPANY_LEVEL_RE.search(sentence):
                continue
            match = _MISSION_CLAUSE_RE.search(sentence)
            if match:
                clause = _CLAUSE_END_RE.split(match.group(1) or "to help " + match.group(2))[0].strip()
                if 12 <= len(clause) <= 140:
                    missions[clause].add(i)
                continue
            if name:
                desc = re.match(rf"^{name}(?:\s*\([^)]*\))?\s+is\s+(?:the|a|an)\s+[^.;!?]+", sentence, re.I)
                if desc:
                    text = re.sub(r"\s*\([^)]*\)", "", desc.group(0))
                    text = _CLAUSE_END_RE.split(text)[0].strip()
                    if 25 <= len(text) <= 160:
                        about[text].add(i)
    if missions:
        clause = max(missions.items(), key=lambda kv: len(kv[1]))[0]
        return f"its mission {clause}"
    if about:
        return "the work itself: " + max(about.items(), key=lambda kv: len(kv[1]))[0]
    return None


def board_slug_candidates(company: str, email: str = "") -> list[str]:
    """Likely public job-board names for a company: squashed name, hyphenated name, email domain."""
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    stem = domain.split(".")[-2] if domain.count(".") >= 1 else ""
    slugs: list[str] = []
    for slug in (normalize_company(company), re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-"), stem):
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs


def fetch_live_board_jobs(company: str, email: str = "", max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> list[dict[str, Any]]:
    """Recent postings from the company's public Greenhouse, Lever or Ashby board (free public APIs).

    Board names are guessed from the company name and email domain; the first board
    that answers with jobs wins. Returns [] when no board is found.
    """
    import asyncio

    import httpx

    from app.services.job_discover.sources.ashby import AshbySource
    from app.services.job_discover.sources.greenhouse import GreenhouseSource
    from app.services.job_discover.sources.lever import LeverSource

    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)

    async def run() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(headers={"User-Agent": "CareerOS/1.0"}, follow_redirects=True) as client:
            for slug in board_slug_candidates(company, email):
                for source in (GreenhouseSource, LeverSource, AshbySource):
                    adapter = source()  # fresh instance: 404s on guessed names must not trip the breaker
                    adapter.max_retries = 1
                    found = await adapter.fetch_jobs(client, slug, {"slug": slug, "company_name": company}, [], cutoff)
                    if found:
                        return [{
                            "company": company,
                            "title": job.title,
                            "description": job.description,
                            "listingUrl": job.source_url or job.apply_url,
                            "datePosted": job.first_published or job.updated_at,
                            "active": "True",
                            "board": f"{adapter.id}:{slug}",
                        } for job in found]
        return []

    return asyncio.run(run())


def _skill_labels(role: OpenRole, limit: int = 3) -> list[str]:
    labels: list[str] = []
    for key in role.have:
        label = SKILL_LABELS.get(key)
        if label and label not in labels:
            labels.append(label)
        if len(labels) == limit:
            break
    return labels


def _join(labels: list[str]) -> str:
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


def _focus_phrase(role: OpenRole) -> str:
    labels = _skill_labels(role)
    if not labels:
        return ""
    return f"The focus on {_join(labels)} is close to what I work on day to day."


def _role_line(role: OpenRole) -> str:
    line = f"•  {role.title}"
    if role.url:
        line += f" ({role.url})"
    labels = _skill_labels(role)
    if labels:
        line += f": {_join(labels)}"
    return line


def _reorder_bullets(body: str, roles: list[OpenRole]) -> str:
    tags = {tag for role in roles for tag in (*role.have, *role.domains)}
    lines = body.split("\n")
    idx = [i for i, line in enumerate(lines) if _BULLET_RE.match(line)]
    if len(idx) < 2 or idx != list(range(idx[0], idx[0] + len(idx))):
        return body

    def relevance(line: str) -> int:
        text = _BULLET_RE.match(line).group(1)
        for highlight, hl_tags in HIGHLIGHTS:
            if highlight[:40] in text:
                return len(hl_tags & tags)
        return 0

    block = [lines[i] for i in idx]
    ordered = sorted(block, key=relevance, reverse=True)  # stable: ties keep original order
    return "\n".join(lines[: idx[0]] + ordered + lines[idx[-1] + 1 :])


def display_company(listed: str, posted: str, body: str) -> str:
    """Best spelling of the company name.

    Recruiter lists and scraped postings often flatten brand casing ("Doordash",
    "Docusign"), while the hand-written template body keeps it ("DoorDash"). Among
    the spellings seen, the one with the most capitals wins; shouting caps are ignored.
    """
    candidates = [c for c in (listed, posted) if c]
    for name in list(candidates):
        candidates += re.findall(rf"\b{re.escape(name)}\b", body, flags=re.IGNORECASE)

    def capitals(name: str) -> int:
        if len(name) > 4 and name.isupper():
            return -1
        return sum(ch.isupper() for ch in name)

    return max(candidates, key=capitals, default="")  # max keeps the first on ties


def tailor_email(email: dict[str, Any], roles: list[OpenRole], mission: str | None = None) -> dict[str, Any]:
    """Return a copy of the email tailored to the top roles, or unchanged if there are none."""
    out = dict(email)
    if not roles:
        out["roleMatched"] = False
        return out
    roles = roles[:TOP_ROLES]
    top = roles[0]
    body = str(email.get("body") or "")
    company = display_company(email.get("company") or "", top.company, body)
    # Reorder resume highlights first: once role bullets are inserted the body has two bullet blocks.
    body = _reorder_bullets(body, roles)

    if len(roles) == 1:
        opening = f"I'm reaching out because I saw the {top.title} opening at {company}"
        if top.url:
            opening += f" ({top.url})"
        opening += ", and it lines up closely with my background."
        focus = _focus_phrase(top)
        if focus:
            opening += f" {focus}"
        ask = f"If you think my background could be a fit for the {top.title} role, or another team at {company}"
    else:
        opening = (f"I'm reaching out because I saw a few recent openings at {company} that line up closely "
                   "with my background:\n\n" + "\n".join(_role_line(r) for r in roles))
        ask = f"If you think my background could be a fit for one of these roles, or another team at {company}"
    body, n = re.subn(r"I'm reaching out because[^\n]*", lambda _: opening, body, count=1)
    if n == 0:
        body = re.sub(r"(I hope you're doing well\.)", lambda m: f"{m.group(1)}\n\n{opening}", body, count=1)
    body = re.sub(r"If you think my background could be a fit for any of your teams",
                  lambda _: ask, body, count=1)

    if mission:
        why = (f"What draws me to {company} is {mission}. Building the systems behind that is the kind of "
               "engineering I enjoy, and where I think my experience would translate well.")
        body = re.sub(r"One of the reasons I'm interested in[^\n]*", lambda _: why, body, count=1)

    out["body"] = body
    out["subject"] = f"Senior Software Engineer at Microsoft | {top.title} at {company}"
    out["roleMatched"] = True
    out["role"] = top.title
    out["roleUrl"] = top.url
    out["roleScore"] = top.score
    out["otherRoles"] = [r.title for r in roles[1:]]
    out["roles"] = [{"title": r.title, "url": r.url, "score": r.score, "posted": r.posted or None} for r in roles]
    out["mission"] = mission
    return out


def tailor_emails(
    emails: list[dict[str, Any]],
    jobs_by_company: dict[str, list[dict[str, Any]]],
    min_score: float = DEFAULT_MIN_SCORE,
    max_age_days: int | None = DEFAULT_MAX_AGE_DAYS,
    live_lookup: LiveLookup | None = None,
    today: date | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Tailor every email; returns (emails, companies with no fitting open role).

    ``live_lookup(company, email)`` is tried for companies with no jobs in
    ``jobs_by_company``; a lookup error is recorded on the email, never swallowed.
    """
    cache: dict[str, tuple[list[OpenRole], str | None, str]] = {}
    unmatched: list[str] = []
    tailored: list[dict[str, Any]] = []
    for email in emails:
        company = email.get("company") or ""
        key = normalize_company(company)
        if key not in cache:
            jobs, source, error = jobs_by_company.get(key, []), "db", ""
            if not jobs and live_lookup is not None:
                source = "live_board"
                try:
                    jobs = live_lookup(company, email.get("email") or "")
                except Exception as exc:  # noqa: BLE001 - reported per company below
                    jobs, error = [], f"live board lookup failed: {exc}"
            roles = rank_roles(jobs, min_score, max_age_days, today)
            cache[key] = (roles, extract_mission(jobs, company) if roles else None, source if jobs else "none")
            if error:
                cache[key] = (roles, None, error)
            if not roles:
                unmatched.append(company)
        roles, mission, source = cache[key]
        out = tailor_email(email, roles, mission)
        out["roleSource"] = source
        tailored.append(out)
    return tailored, unmatched
