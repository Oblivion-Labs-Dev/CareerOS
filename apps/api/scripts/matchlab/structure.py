"""Deterministic structure extraction for jobs and the resume.

The central lesson from the failed coverage scorer is here. Representing a job
as a flat bag of skills

    ["Java", "AWS", "React", "CI/CD", "Kubernetes"]

loses the thing that actually decides fit. A frontend posting listing React,
TypeScript, testing and CI/CD scored 100% against this candidate while a backend
posting scored 61.9%, because the frontend posting happened to list fewer, more
generic requirements and the candidate nominally satisfies all of them.

So a job is represented as a *shape* instead:

    role_family        what kind of engineer the posting wants
    seniority          what level
    primary_work       the two or three things the job is mostly about
    must_have          requirements with weights
    preferred          requirements with lower weights

A role-family mismatch can then outweigh any amount of generic keyword overlap,
which is the specific failure being fixed.

Everything here is deterministic: regex and table lookups, no model, no network,
no sampling. Same input, same output, measured in single-digit milliseconds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Role families
# ---------------------------------------------------------------------------
# Cues are ordered by how strongly they imply the family. A title cue is worth
# far more than a body cue: a posting titled "Android Engineer" is an Android
# job whatever its body says about microservices, whereas a body that mentions
# Android once may just be describing a client the team supports.

ROLE_FAMILIES: dict[str, dict[str, tuple[str, ...]]] = {
    "frontend": {
        "title": (r"front.?end", r"\bui\b", r"web developer", r"javascript engineer"),
        "body": (r"react", r"typescript", r"css", r"single.page", r"browser",
                 r"responsive design", r"figma", r"accessibility"),
    },
    "mobile": {
        "title": (r"android", r"\bios\b", r"mobile", r"react native", r"flutter"),
        "body": (r"jetpack compose", r"swiftui", r"app store", r"play store",
                 r"mobile app"),
    },
    "backend": {
        "title": (r"back.?end", r"server.side", r"\bapi engineer"),
        "body": (r"microservice", r"\brest\b", r"grpc", r"database", r"\bapi\b",
                 r"server", r"backend service"),
    },
    "platform": {
        "title": (r"platform", r"developer experience", r"\bdevex\b", r"tooling",
                  r"developer productivity"),
        "body": (r"internal platform", r"developer platform", r"ci/cd",
                 r"build system", r"golden path", r"paved road"),
    },
    "infrastructure": {
        "title": (r"infrastructure", r"\bcloud engineer", r"\bdevops\b", r"systems engineer"),
        "body": (r"terraform", r"kubernetes", r"provisioning", r"iac",
                 r"infrastructure as code", r"cloud infrastructure"),
    },
    "sre": {
        "title": (r"\bsre\b", r"site reliability", r"reliability engineer",
                  r"production engineer"),
        "body": (r"on.call", r"incident", r"slo\b", r"error budget", r"postmortem",
                 r"observability", r"uptime"),
    },
    "data": {
        "title": (r"data engineer", r"analytics engineer", r"data scientist",
                  r"data platform"),
        "body": (r"\betl\b", r"data pipeline", r"warehouse", r"spark", r"airflow",
                 r"\bdbt\b", r"snowflake"),
    },
    "ml": {
        "title": (r"machine learning", r"\bml\b", r"\bai engineer", r"applied scientist",
                  r"\bmlops\b", r"research engineer"),
        "body": (r"model training", r"inference", r"pytorch", r"tensorflow",
                 r"feature store", r"embeddings", r"\bllm\b"),
    },
    "security": {
        "title": (r"security", r"\bappsec\b", r"detection", r"threat", r"trust and safety"),
        "body": (r"threat model", r"vulnerabilit", r"siem", r"detection engineering",
                 r"compliance", r"risk detection", r"insider risk"),
    },
    "fullstack": {
        "title": (r"full.?stack",),
        "body": (r"end.to.end ownership", r"front.?end and back.?end"),
    },
}

#: Which families are close enough that a mismatch between them is mild. Used so
#: an infrastructure candidate is not treated as equally wrong for a platform
#: role as for an Android role.
FAMILY_AFFINITY: dict[tuple[str, str], float] = {
    ("backend", "platform"): 0.75,
    ("backend", "infrastructure"): 0.70,
    ("backend", "sre"): 0.65,
    ("backend", "security"): 0.60,
    ("backend", "data"): 0.55,
    ("backend", "ml"): 0.50,
    ("backend", "fullstack"): 0.60,
    ("platform", "infrastructure"): 0.90,
    ("platform", "sre"): 0.80,
    ("platform", "security"): 0.55,
    ("platform", "fullstack"): 0.40,
    ("infrastructure", "sre"): 0.85,
    ("infrastructure", "security"): 0.55,
    ("sre", "security"): 0.50,
    ("data", "ml"): 0.70,
    ("data", "platform"): 0.50,
    ("ml", "security"): 0.35,
    ("fullstack", "frontend"): 0.70,
    ("fullstack", "mobile"): 0.35,
    ("frontend", "mobile"): 0.55,
}


def family_affinity(a: str, b: str) -> float:
    """How related two role families are, 0..1. Symmetric, 1.0 for identical."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.5  # unknown shape: neither reward nor punish
    return FAMILY_AFFINITY.get((a, b)) or FAMILY_AFFINITY.get((b, a)) or 0.25


SENIORITY_LEVELS: tuple[tuple[str, int], ...] = (
    (r"\bintern\b|\bnew grad\b|\bgraduate\b", 0),
    (r"\bjunior\b|\bassociate\b|\bentry.level\b|\bi{1,2}\b(?!\w)", 1),
    (r"\bsenior\b|\bsr\.?\b|\bsenior[- ]level\b|\biii\b", 3),
    (r"\bstaff\b|\bprincipal\b|\blead\b|\barchitect\b|\bdistinguished\b", 4),
    (r"\bmanager\b|\bdirector\b|\bhead of\b|\bvp\b", 5),
)
DEFAULT_SENIORITY = 2  # plain "Software Engineer"


def detect_seniority(title: str) -> int:
    for pattern, level in SENIORITY_LEVELS:
        if re.search(pattern, title, re.I):
            return level
    return DEFAULT_SENIORITY


def detect_role_family(title: str, body: str) -> tuple[str, dict[str, float]]:
    """Best-guess role family plus the full score vector.

    Title cues are weighted an order of magnitude above body cues, and body
    cues saturate, so a long posting cannot win on repetition alone.
    """
    title_l, body_l = title.lower(), body.lower()
    scores: dict[str, float] = {}
    for family, cues in ROLE_FAMILIES.items():
        title_hits = sum(1 for c in cues["title"] if re.search(c, title_l))
        body_hits = sum(1 for c in cues["body"] if re.search(c, body_l))
        # Saturating body contribution: 0 -> 0, 1 -> .35, 3 -> .69, 8 -> .89
        body_signal = 1.0 - (0.72 ** body_hits) if body_hits else 0.0
        scores[family] = title_hits * 3.0 + body_signal
    best = max(scores, key=lambda k: scores[k])
    return (best if scores[best] > 0.5 else ""), scores


# ---------------------------------------------------------------------------
# Requirement extraction
# ---------------------------------------------------------------------------

_MUST_MARKERS = re.compile(
    r"(required|must have|minimum qualifications|basic qualifications|you have|"
    r"what you.ll need|requirements|qualifications)", re.I
)
_NICE_MARKERS = re.compile(
    r"(preferred|nice to have|bonus|plus|desired|good to have|ideally)", re.I
)
_RESP_MARKERS = re.compile(
    r"(responsibilities|what you.ll do|the role|about the role|day to day|"
    r"you will|in this role)", re.I
)

_BULLET = re.compile(r"^\s*(?:[-*•●▪–]|\d+[.)])\s+(.{12,400})$", re.M)


def _segment(description: str) -> dict[str, str]:
    """Split a posting into must / preferred / responsibilities / rest.

    Deliberately crude. Postings are not consistently structured, and a parser
    that tries to be clever about them is a parser that fails silently on the
    next board. Anything unrecognised stays in "rest" and is still scored.
    """
    lines = description.splitlines()
    buckets = {"must": [], "preferred": [], "responsibilities": [], "rest": []}
    current = "rest"
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # A short line that looks like a heading switches the active bucket.
        if len(stripped) < 80:
            if _NICE_MARKERS.search(stripped):
                current = "preferred"
                continue
            if _MUST_MARKERS.search(stripped):
                current = "must"
                continue
            if _RESP_MARKERS.search(stripped):
                current = "responsibilities"
                continue
        buckets[current].append(stripped)
    return {k: "\n".join(v) for k, v in buckets.items()}


def extract_requirements(text: str) -> list[str]:
    """Requirement-like lines. Falls back to sentences when there are no bullets."""
    bullets = [m.group(1).strip() for m in _BULLET.finditer(text)]
    if bullets:
        return bullets
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if 25 < len(s.strip()) < 400]


@dataclass
class JobShape:
    title: str
    company: str
    description: str
    role_family: str = ""
    family_scores: dict[str, float] = field(default_factory=dict)
    seniority: int = DEFAULT_SENIORITY
    must_have: list[str] = field(default_factory=list)
    preferred: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title, "company": self.company,
            "roleFamily": self.role_family, "seniority": self.seniority,
            "mustHave": self.must_have[:12], "preferred": self.preferred[:12],
            "responsibilities": self.responsibilities[:12],
        }


def parse_job(title: str, company: str, description: str) -> JobShape:
    sections = _segment(description)
    family, scores = detect_role_family(title, description)
    return JobShape(
        title=title, company=company, description=description,
        role_family=family, family_scores=scores,
        seniority=detect_seniority(title),
        must_have=extract_requirements(sections["must"] or sections["rest"]),
        preferred=extract_requirements(sections["preferred"]),
        responsibilities=extract_requirements(
            sections["responsibilities"] or sections["rest"]
        ),
        sections=sections,
    )


# ---------------------------------------------------------------------------
# Resume side
# ---------------------------------------------------------------------------

@dataclass
class Evidence:
    """One thing the candidate can point at, and how strongly."""

    text: str
    source: str            # professional | project | skills | education
    company: str = ""
    tier: float = 1.0      # strength multiplier for this kind of evidence

    @property
    def is_professional(self) -> bool:
        return self.source == "professional"


@dataclass
class ResumeShape:
    headline: str
    professional: list[Evidence] = field(default_factory=list)
    projects: list[Evidence] = field(default_factory=list)
    skills: list[Evidence] = field(default_factory=list)
    role_family: str = ""
    seniority: int = 3

    @property
    def all_evidence(self) -> list[Evidence]:
        return self.professional + self.projects + self.skills


#: How much weight each kind of evidence carries. These are *parameters*, swept
#: in the ablation study rather than asserted - the brief is explicit that
#: hard-coding a multiplier and declaring success is not an experiment.
DEFAULT_TIERS = {"professional": 1.0, "project": 0.45, "skills": 0.25, "education": 0.2}


def build_resume_shape(
    corpus: list[dict[str, Any]],
    headline: str = "",
    tiers: dict[str, float] | None = None,
) -> ResumeShape:
    """Turn the story corpus into weighted evidence.

    The corpus already carries the distinction that matters: every story is
    tagged professional or personal-project, and that tag was set from the
    source material rather than inferred. Kubernetes evidence that exists only
    in a side project must not read as production ownership.
    """
    tiers = tiers or DEFAULT_TIERS
    shape = ResumeShape(headline=headline)
    for story in corpus:
        evidence_kind = "professional" if story.get("evidence") == "professional" else "project"
        text = " ".join(filter(None, [
            story.get("title", ""), story.get("headline", ""),
            " ".join(story.get("technologies") or []),
            " ".join(story.get("concepts") or []),
        ]))
        item = Evidence(
            text=text, source=evidence_kind,
            company=story.get("company", ""), tier=tiers[evidence_kind],
        )
        (shape.professional if evidence_kind == "professional" else shape.projects).append(item)
    return shape
