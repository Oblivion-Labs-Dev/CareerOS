"""Tailor recruiter outreach emails to the company's currently open roles.

Plain code, no model calls: open roles come from the scraped ``aa_discovered_job``
entities, each role is ranked against the resume with ``profile_match``, and the
best fit is written into the email (subject, opening line, ask, and the order of
the resume highlights). A company with no open role that fits keeps its original
email untouched and is reported as unmatched, so nothing is invented.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.services.application_assistant.profile_match import profile_match

DEFAULT_MIN_SCORE = 60.0

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


def rank_roles(jobs: Iterable[dict[str, Any]], min_score: float = DEFAULT_MIN_SCORE) -> list[OpenRole]:
    """Fitting roles, best first. Blocked roles and duplicate titles are dropped."""
    best: dict[str, OpenRole] = {}
    for job in jobs:
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
            posted=str(job.get("datePosted") or ""),
        )
        key = title.lower()
        current = best.get(key)
        if current is None or (role.score, role.posted) > (current.score, current.posted):
            best[key] = role
    return sorted(best.values(), key=lambda r: (r.score, r.posted), reverse=True)


def _focus_phrase(role: OpenRole) -> str:
    labels: list[str] = []
    for key in role.have:
        label = SKILL_LABELS.get(key)
        if label and label not in labels:
            labels.append(label)
        if len(labels) == 3:
            break
    if not labels:
        return ""
    joined = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]
    return f"The focus on {joined} is close to what I work on day to day."


def _reorder_bullets(body: str, role: OpenRole) -> str:
    tags = set(role.have) | set(role.domains)
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


def tailor_email(email: dict[str, Any], roles: list[OpenRole]) -> dict[str, Any]:
    """Return a copy of the email tailored to the top role, or unchanged if there is none."""
    out = dict(email)
    if not roles:
        out["roleMatched"] = False
        return out
    top = roles[0]
    body = str(email.get("body") or "")
    company = display_company(email.get("company") or "", top.company, body)

    opening = f"I'm reaching out because I saw the {top.title} opening at {company}"
    if top.url:
        opening += f" ({top.url})"
    opening += ", and it lines up closely with my background."
    focus = _focus_phrase(top)
    if focus:
        opening += f" {focus}"
    body, n = re.subn(r"I'm reaching out because[^\n]*", lambda _: opening, body, count=1)
    if n == 0:
        body = re.sub(r"(I hope you're doing well\.)", lambda m: f"{m.group(1)}\n\n{opening}", body, count=1)

    ask = f"If you think my background could be a fit for the {top.title} role"
    if len(roles) > 1:
        ask += f" (or the {roles[1].title} role)"
    ask += f", or another team at {company}"
    body = re.sub(r"If you think my background could be a fit for any of your teams",
                  lambda _: ask, body, count=1)

    out["body"] = _reorder_bullets(body, top)
    out["subject"] = f"Senior Software Engineer at Microsoft | {top.title} at {company}"
    out["roleMatched"] = True
    out["role"] = top.title
    out["roleUrl"] = top.url
    out["roleScore"] = top.score
    out["otherRoles"] = [r.title for r in roles[1:3]]
    return out


def tailor_emails(
    emails: list[dict[str, Any]],
    jobs_by_company: dict[str, list[dict[str, Any]]],
    min_score: float = DEFAULT_MIN_SCORE,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Tailor every email; returns (emails, companies with no fitting open role)."""
    cache: dict[str, list[OpenRole]] = {}
    unmatched: list[str] = []
    tailored: list[dict[str, Any]] = []
    for email in emails:
        key = normalize_company(email.get("company") or "")
        if key not in cache:
            cache[key] = rank_roles(jobs_by_company.get(key, []), min_score)
            if not cache[key]:
                unmatched.append(email.get("company") or "")
        tailored.append(tailor_email(email, cache[key]))
    return tailored, unmatched
