"""Read-only loader and index over career.json."""
from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

#: Statuses a resume claim may cite. supported_variant is usable only with its
#: own ID attached, which every bullet already requires.
USABLE = frozenset({"supported", "supported_variant"})
#: sparse_evidence may establish that a project existed, nothing more.
EXISTENCE_ONLY = frozenset({"sparse_evidence"})
BLOCKED = frozenset({"needs_reconciliation", "guardrail"})

#: Skill groups that name concrete technologies. architecture_systems holds
#: concepts ("System Design") and is matched for retrieval, not policed.
TECH_GROUPS = ("languages", "cloud_platform", "ai_ml_security")
PERSONAL_EMPLOYMENT_ID = "personal"


def default_path() -> Path:
    configured = os.environ.get("CAREEROS_CAREER_JSON")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[5] / "data" / "profile" / "career.json"


@dataclass(frozen=True)
class Evidence:
    id: str
    type: str
    claim: str
    status: str
    tags: tuple[str, ...]
    project_id: str
    employment_id: str
    company: str

    @property
    def usable(self) -> bool:
        return self.status in USABLE

    def brief(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "status": self.status, "claim": self.claim, "tags": list(self.tags)}


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    employment_id: str
    company: str
    summary: str
    technologies: tuple[str, ...]
    details: tuple[str, ...]
    ownership: tuple[str, ...]
    domains: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    @property
    def personal(self) -> bool:
        return self.employment_id == PERSONAL_EMPLOYMENT_ID


@dataclass
class CareerStore:
    data: dict[str, Any]
    digest: str
    path: str
    evidence: dict[str, Evidence] = field(default_factory=dict)
    projects: dict[str, Project] = field(default_factory=dict)
    employment: dict[str, dict[str, Any]] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        """A copy callers may read freely; the cached original stays untouched."""
        return deepcopy(self.data)

    def project_evidence(self, project_id: str) -> list[Evidence]:
        return [self.evidence[i] for i in self.projects[project_id].evidence_ids]

    def project_is_sparse(self, project_id: str) -> bool:
        records = self.project_evidence(project_id)
        return bool(records) and not any(e.usable for e in records)

    @property
    def technologies(self) -> tuple[str, ...]:
        skills = self.data.get("skills") or {}
        terms = {t for group in TECH_GROUPS for t in skills.get(group) or [] if isinstance(t, str)}
        for project in self.projects.values():
            terms.update(project.technologies)
        return tuple(sorted(terms, key=lambda t: (-len(t), t.casefold())))

    @property
    def concepts(self) -> tuple[str, ...]:
        skills = self.data.get("skills") or {}
        terms = set(skills.get("architecture_systems") or [])
        for job in self.employment.values():
            terms.update(job.get("domains") or [])
        return tuple(sorted(terms, key=lambda t: (-len(t), t.casefold())))

    @property
    def conflicts(self) -> list[dict[str, Any]]:
        return [c for c in self.data.get("conflicts") or [] if c.get("resolution") != "resolved"]

    @property
    def writing_style(self) -> dict[str, Any]:
        return (self.data.get("meta") or {}).get("writing_style") or {}

    @property
    def company_names(self) -> tuple[str, ...]:
        return tuple(job["company"] for job in self.employment.values())


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(v) for v in value if isinstance(v, (str, int, float)))
    return ()


def _index(data: dict[str, Any], digest: str, path: str) -> CareerStore:
    store = CareerStore(data=data, digest=digest, path=path)
    seen: set[str] = set()

    def add_project(raw: dict[str, Any], employment_id: str, company: str, domains: tuple[str, ...]) -> None:
        detail_fields = ("problem", "architecture", "scale", "impact", "reliability", "scope", "decisions", "tradeoffs", "validation")
        ids = []
        for ev in raw.get("evidence") or []:
            if ev["id"] in seen:
                raise ValueError(f"Duplicate evidence id in career.json: {ev['id']}")
            seen.add(ev["id"])
            ids.append(ev["id"])
            store.evidence[ev["id"]] = Evidence(
                id=ev["id"], type=str(ev.get("type") or ""), claim=str(ev.get("claim") or ""),
                status=str(ev.get("status") or ""), tags=tuple(ev.get("tags") or ()),
                project_id=raw["id"], employment_id=employment_id, company=company)
        store.projects[raw["id"]] = Project(
            id=raw["id"], name=str(raw.get("name") or raw["id"]), employment_id=employment_id, company=company,
            summary=str(raw.get("summary") or ""), technologies=_strings(raw.get("technologies")),
            details=tuple(s for f in detail_fields for s in _strings(raw.get(f))),
            ownership=_strings(raw.get("ownership")), domains=domains, evidence_ids=tuple(ids))

    for job in data.get("employment") or []:
        store.employment[job["id"]] = {k: v for k, v in job.items() if k != "projects"}
        for project in job.get("projects") or []:
            add_project(project, job["id"], job["company"], tuple(job.get("domains") or ()))
    for project in data.get("personal_projects") or []:
        add_project(project, PERSONAL_EMPLOYMENT_ID, "", ())
    positioning = (data.get("person") or {}).get("positioning") or {}
    # Canonical paths person.positioning.experience / .primary, cited like any claim.
    if positioning.get("experience"):
        store.evidence["person.positioning.experience"] = Evidence(
            id="person.positioning.experience", type="positioning", claim=f"{positioning['experience']} of experience",
            status="supported", tags=("summary",), project_id="", employment_id="", company="")
    if positioning.get("primary"):
        store.evidence["person.positioning.primary"] = Evidence(
            id="person.positioning.primary", type="positioning", claim="Focus areas: " + ", ".join(positioning["primary"]),
            status="supported", tags=("summary",), project_id="", employment_id="", company="")
    return store


@lru_cache(maxsize=4)
def _load(path: str, digest: str) -> CareerStore:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if (data.get("meta") or {}).get("document_type") != "career_evidence_store":
        raise ValueError("career.json is not a Career OS evidence store.")
    return _index(data, digest, path)


def load_store(path: Path | None = None) -> CareerStore:
    target = (path or default_path()).resolve()
    if not target.is_file():
        raise FileNotFoundError(f"career.json not found at {target}. Set CAREEROS_CAREER_JSON.")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return _load(str(target), digest)


_WORD = re.compile(r"[a-z0-9][a-z0-9+#.]*")


def term_pattern(term: str) -> re.Pattern[str]:
    flags = 0 if (term.isupper() and len(term) <= 4) else re.I
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", flags)


def mentions(text: str, term: str) -> bool:
    return len(term) > 1 and bool(term_pattern(term).search(text))


def tokens(text: str) -> set[str]:
    out = set()
    for word in _WORD.findall(text.casefold()):
        word = word.rstrip(".")
        out.add(word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word)
    return out
