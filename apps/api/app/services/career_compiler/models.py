"""Typed JSON passed between compiler stages."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

SECTIONS = ("responsibilities", "required_qualifications", "preferred_qualifications", "technologies", "domain",
            "architecture", "leadership", "ai_ml")
Section_ = Literal["responsibilities", "required_qualifications", "preferred_qualifications", "technologies", "domain",
                   "architecture", "leadership", "ai_ml"]
Importance = Literal["high", "medium", "low"]
Strength = Literal["strong", "moderate", "weak"]


class JobInput(BaseModel):
    text: str
    url: str = ""
    title: str = ""
    company: str = ""


class Requirement(BaseModel):
    id: str
    section: Section_
    original_text: str
    normalized_requirement: str
    skills: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    importance: Importance = "medium"
    offset: int = 0
    required: bool = False
    #: Themes this requirement shares with at least one other requirement in the same posting.
    repeated_themes: list[str] = Field(default_factory=list)
    #: Career vocabulary the evidence query maps this requirement to. Equivalent terms count like skills;
    #: adjacent terms are related work and can only ever produce weak matches.
    query_terms: list[str] = Field(default_factory=list)
    adjacent_terms: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _required_from_section(self) -> "Requirement":
        if self.section == "required_qualifications":
            self.required = True
        return self


class JobDescription(BaseModel):
    """jd.json: the job's requirements. Every original_text is verbatim from the posting."""
    id: str
    title: str = ""
    company: str = ""
    url: str = ""
    text: str
    requirements: list[Requirement]
    source: Literal["deepseek", "deterministic"] = "deterministic"
    dropped: list[str] = Field(default_factory=list)
    repeated_themes: list[str] = Field(default_factory=list)


class RequirementQuery(BaseModel):
    requirement_id: str
    terms: list[str] = Field(default_factory=list)
    adjacent: list[str] = Field(default_factory=list)
    evidence_types: list[str] = Field(default_factory=list)


class EvidenceQuery(BaseModel):
    """What DeepSeek says each requirement needs, restricted to career.json's own vocabulary. Career OS runs it."""
    jd_id: str = ""
    version: str = ""
    source: Literal["deepseek", "none"] = "none"
    requirements: list[RequirementQuery] = Field(default_factory=list)
    dropped_terms: list[str] = Field(default_factory=list)


class JobAnalysis(BaseModel):
    """A flat view of jd.json used for skill ordering. Derived, never asked of the LLM."""
    target_role: str = ""
    company: str = ""
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    source: Literal["deepseek", "deterministic"] = "deterministic"


class EvidenceMatch(BaseModel):
    requirement_id: str
    evidence_id: str
    project_id: str
    company: str
    status: str
    claim: str
    strength: Strength
    score: float
    matched: list[str] = Field(default_factory=list)


class Candidate(BaseModel):
    evidence_id: str
    type: str
    status: str
    claim: str
    score: float
    requirement_ids: list[str] = Field(default_factory=list)


class ProjectCandidate(BaseModel):
    project_id: str
    name: str
    company: str
    employment_id: str
    score: float
    coverage: dict[str, Strength] = Field(default_factory=dict)
    existence_only: bool = False
    evidence: list[Candidate] = Field(default_factory=list)
    blocked: list[Candidate] = Field(default_factory=list)


class Retrieval(BaseModel):
    projects: list[ProjectCandidate]
    matches: dict[str, list[EvidenceMatch]] = Field(default_factory=dict)
    guardrails: list[str] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)
    store_digest: str
    version: str = ""
    excluded: list[str] = Field(default_factory=list)


class RankedProject(BaseModel):
    project_id: str
    score: float
    reason: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class Ranking(BaseModel):
    projects: list[RankedProject]
    source: Literal["deepseek", "deterministic"] = "deterministic"
    target_role: str = ""
    primary_themes: list[str] = Field(default_factory=list)


class PlannedProject(BaseModel):
    project_id: str
    employment_id: str
    reason: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    score: float = 0
    locked: bool = False
    pinned: bool = False
    lines: int = Field(default=2, ge=1, le=3)
    #: Why the planner spent page space on it: answers the JD, or (once the JD is covered) strong career evidence,
    #: or a capability the page did not show yet.
    selection: Literal["jd_match", "career_signal", "diversity"] = "jd_match"


class SectionBudget(BaseModel):
    """Decided by the planner per JD before writing. Lines are the template's own Word-calibrated lines."""
    summary: int = 1
    microsoft: int = 0
    amazon: int = 0
    earlier: int = 0
    projects: int = 0
    capacity_lines: int = 0
    planned_lines: int = 0


class CoverageItem(BaseModel):
    requirement_id: str
    project_ids: list[str] = Field(default_factory=list)
    strength: Strength | None = None
    #: planned | supported_not_planned | no_supported_evidence
    status: str = "planned"


class ResumePlan(BaseModel):
    target_role: str = ""
    jd_themes: list[str] = Field(default_factory=list)
    primary_themes: list[str] = Field(default_factory=list)
    selected_projects: list[PlannedProject] = Field(default_factory=list)
    section_budget: SectionBudget = Field(default_factory=SectionBudget)
    coverage_plan: list[CoverageItem] = Field(default_factory=list)


class Bullet(BaseModel):
    id: str
    employment_id: str
    project_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    locked: bool = False
    name: str = ""
    requirements: list[dict] = Field(default_factory=list)
    lint: list[dict] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def jd_requirement_ids(self) -> list[str]:
        """Requirements this bullet supports. Weak (adjacent) matches stay in `requirements` for the UI only."""
        return [r["id"] for r in self.requirements if isinstance(r, dict) and r.get("strength") in ("strong", "moderate")]


class ValidationIssue(BaseModel):
    bullet_id: str
    code: str
    message: str
    #: The offending text, e.g. "1M TPS", and the evidence wording the bullet was allowed to use instead.
    claim: str = ""
    allowed_evidence: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def error(self) -> str:
        return self.code


class Section(BaseModel):
    employment_id: str
    company: str
    role: str
    location: str = ""
    start: str = ""
    end: str = ""
    bullets: list[Bullet] = Field(default_factory=list)


class ResumeDocument(BaseModel):
    """resume.json: content only. Layout comes from the golden DOCX template."""
    method: Literal["career-compiler-v1"] = "career-compiler-v1"
    store_digest: str
    jd_id: str = ""
    template_digest: str = ""
    target_role: str = ""
    summary: Bullet | None = None
    sections: list[Section] = Field(default_factory=list)
    featured: list[Bullet] = Field(default_factory=list)
    skills: dict[str, list[str]] = Field(default_factory=dict)
    education: list[dict] = Field(default_factory=list)
    max_pages: int = 1

    def bullets(self) -> list[Bullet]:
        return [b for s in self.sections for b in s.bullets] + list(self.featured)
