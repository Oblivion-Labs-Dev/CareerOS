"""Is a posting one the candidate should see?

Relevance is the same judgement Autopilot makes before it applies: the shared
software-role filter (``software_role_rejection``) plus the level flags, so a
role Markets surfaces is one Autopilot would accept. Senior, SDE III, Staff and
level-less titles ("Backend Engineer", "AI Engineer", "Member of Technical
Staff") are relevant; explicitly junior or mid levels (I, II, new grad) are not,
matching the apply-time level gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.application_assistant.job_filter_ranker import role_level_flags, software_role_rejection

_BELOW_SENIOR = re.compile(
    r"\b(junior|jr\.?|entry[\s-]level|new\s+grad(?:uate)?|graduate|early\s+career|university|associate)\b"
    r"|\b(?:engineer|developer|sde|swe|scientist)\s*(?:i{1,2}|[12])\b"
    r"|\b(?:i{1,2}|[12])\s*$"
    r"|\blevel\s*[12]\b",
    re.I,
)
_MTS = re.compile(r"\bmember\s+of\s+(?:the\s+)?technical\s+staff\b", re.I)

TAG_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Agentic AI", re.compile(r"\bagent(?:s|ic)?\b|\bmulti-agent\b|\bai\s+agents?\b", re.I)),
    ("AI/ML", re.compile(r"\b(?:ai|ml|llm|llms|genai|gen\s*ai|generative|machine\s+learning|deep\s+learning|applied\s+ai|inference|model)\b", re.I)),
    ("Backend", re.compile(r"\bback[\s-]?end\b|\bapi(?:s)?\b|\bservices?\b", re.I)),
    ("Platform", re.compile(r"\bplatform\b|\bdeveloper\s+(?:platform|productivity|experience)\b", re.I)),
    ("Distributed Systems", re.compile(r"\bdistributed\b|\bstorage\b|\bstreaming\b|\bdatabase\b|\bscal(?:e|able|ability)\b", re.I)),
    ("Infrastructure", re.compile(r"\binfrastructure\b|\bcloud\b|\bsre\b|\bsite\s+reliability\b|\bkubernetes\b|\bdevops\b", re.I)),
)


@dataclass
class Relevance:
    relevant: bool
    level: str
    reason: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {"relevant": self.relevant, "level": self.level, "reason": self.reason, "tags": self.tags}


def job_level(title: str) -> str:
    lowered = (title or "").lower()
    is_senior, is_staff = role_level_flags(lowered)
    if is_senior:
        return "senior"
    if is_staff:
        return "staff"
    if _BELOW_SENIOR.search(lowered):
        return "below-senior"
    return "unleveled"


def tags_for(title: str, description: str = "") -> list[str]:
    title_tags = [name for name, pattern in TAG_RULES if pattern.search(title or "")]
    if len(title_tags) >= 2 or not description:
        return title_tags
    # The description only adds a tag the title is silent on, and only for the
    # specific themes: every posting mentions "services" and "scale".
    head = (description or "")[:4000]
    extra = [
        name for name, pattern in TAG_RULES
        if name in ("Agentic AI", "AI/ML", "Distributed Systems") and name not in title_tags and pattern.search(head)
    ]
    return title_tags + extra[: 2 - len(title_tags)]


def assess(title: str, description: str = "") -> Relevance:
    title = (title or "").strip()
    rejection = software_role_rejection(title) if not _MTS.search(title) else None
    level = job_level(title)
    tags = tags_for(title, description)
    if rejection:
        return Relevance(False, level, rejection, tags)
    if level == "below-senior":
        return Relevance(False, level, f"Role '{title}' is below Senior level", tags)
    return Relevance(True, level, "", tags)
