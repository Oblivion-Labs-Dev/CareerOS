"""The evaluation set, and the adversarial cases that guard against known failures.

Labels are 2 / 1 / 0 (apply, review, skip) with a recorded reason, because a
label whose justification is lost cannot be audited later and this project has
already been burned once by a silently contaminated label set: matching
"platform" in a title put "Staff Android Software Engineer, Cash App Consumer
Platform" in the group meant to represent the candidate's own domain, and the
resulting separation metric measured nothing.

Bootstrap labels come from the job *title*, which is the one field postings are
reliably honest about. They are explicitly provisional - `needs_human` marks the
ones a person should confirm, and `label_source` records where each came from so
model-derived labels can never be silently mistaken for human ones.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

API_ROOT = Path(__file__).resolve().parents[2]
DB = API_ROOT / "data" / "career_os.db"
LABELS_PATH = API_ROOT / "data" / "matchlab_labels.json"

APPLY, REVIEW, SKIP = 2, 1, 0


@dataclass
class Pair:
    """One resume-to-job decision to be scored."""

    id: str
    company: str
    title: str
    description: str
    label: int | None = None
    reason: str = ""
    label_source: str = "rule"      # rule | human | mistral
    needs_human: bool = True
    tags: list[str] = field(default_factory=list)

    @property
    def binary(self) -> int | None:
        """APPLY versus SKIP. REVIEW is excluded, deliberately.

        Grouping REVIEW with SKIP looked reasonable and was wrong: it counted
        every posting the labeller could not classify as a negative, so a
        scorer was penalised for ranking "Staff Software Engineer" highly when
        nobody had established whether that job was a good fit. Measured, the
        apparent false positives at the top of the ranking were almost entirely
        these unknowns.

        Ground truth we do not have is missing data, not a negative label - the
        same distinction that matters for unscored jobs in the queue.
        """
        if self.label is None or self.label == REVIEW:
            return None
        return int(self.label == APPLY)


# ---------------------------------------------------------------------------
# Bootstrap labelling
# ---------------------------------------------------------------------------
# The candidate is a senior backend / platform / infrastructure / security
# engineer. These rules encode only what a title states outright.

_SKIP_TITLE = [
    (r"android|\bios\b|mobile|react native|flutter", "mobile role; no mobile evidence"),
    (r"front.?end|\bui engineer|web developer", "frontend-only role"),
    (r"data scientist|research scientist", "research/DS role, not engineering"),
    (r"\bmanager\b|\bdirector\b|head of|\bvp\b", "management, not IC engineering"),
    (r"designer|recruiter|sales|marketing|product manager", "not an engineering role"),
    (r"\bintern\b|new grad|graduate program", "seniority far below candidate"),
    (r"salesforce|workday|servicenow|netsuite|sap\b", "ERP/SaaS configuration role"),
]

_APPLY_TITLE = [
    (r"back.?end", "backend role, the candidate's core domain"),
    (r"\bplatform\b", "platform engineering, directly evidenced"),
    (r"infrastructure", "infrastructure role, directly evidenced"),
    (r"\bsre\b|site reliability|reliability engineer", "SRE, evidenced by on-call and incident work"),
    (r"distributed", "distributed systems, the strongest evidence area"),
    (r"security engineer|detection engineer", "security platform, current employment"),
]

_SENIOR = re.compile(r"senior|staff|principal|lead|sr\.?\b|\biii\b", re.I)


def bootstrap_label(title: str) -> tuple[int, str, bool]:
    """Provisional label from the title alone. Returns (label, reason, needs_human)."""
    for pattern, reason in _SKIP_TITLE:
        if re.search(pattern, title, re.I):
            return SKIP, reason, False  # title-level mismatches are unambiguous

    for pattern, reason in _APPLY_TITLE:
        if re.search(pattern, title, re.I):
            if _SENIOR.search(title):
                return APPLY, reason, True
            return REVIEW, f"{reason}, but seniority below senior", True

    if re.search(r"software engineer|swe\b", title, re.I):
        return REVIEW, "generic engineering title; fit depends on the body", True
    return REVIEW, "title does not identify a role family", True


def load_pairs(limit: int = 60, min_chars: int = 2500) -> list[Pair]:
    """A diverse evaluation set drawn from real discovered jobs.

    Sampled across companies rather than taken in table order, so the set is not
    dominated by whichever employer happens to post most.
    """
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT payload FROM entities WHERE entity_type='aa_discovered_job'"
    ).fetchall()

    by_company: dict[str, list[Pair]] = {}
    for (payload,) in rows:
        job = json.loads(payload)
        description = str(job.get("description") or "")
        title = str(job.get("title") or "")
        company = str(job.get("company") or "")
        if len(description) < min_chars or not title or not company:
            continue
        label, reason, needs_human = bootstrap_label(title)
        by_company.setdefault(company, []).append(
            Pair(id=str(job.get("id")), company=company, title=title,
                 description=description, label=label, reason=reason,
                 needs_human=needs_human)
        )

    # Round-robin across companies for diversity.
    out: list[Pair] = []
    queues = sorted(by_company.values(), key=len, reverse=True)
    index = 0
    while len(out) < limit and any(index < len(q) for q in queues):
        for queue in queues:
            if index < len(queue):
                out.append(queue[index])
                if len(out) >= limit:
                    break
        index += 1
    return out


def load_human_labels() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def apply_human_labels(pairs: list[Pair]) -> int:
    """Overlay confirmed labels. Human labels always win over rule or model ones."""
    human = load_human_labels()
    applied = 0
    for pair in pairs:
        record = human.get(pair.id)
        if not record:
            continue
        pair.label = int(record["label"])
        pair.reason = record.get("reason", pair.reason)
        pair.label_source = "human"
        pair.needs_human = False
        applied += 1
    return applied


def save_human_label(pair_id: str, label: int, reason: str) -> None:
    existing = load_human_labels()
    existing[pair_id] = {"label": int(label), "reason": reason, "source": "human"}
    LABELS_PATH.write_text(json.dumps(existing, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Adversarial regression cases
# ---------------------------------------------------------------------------
# Synthetic by design. Each isolates one failure mode with everything else held
# constant, which real postings never do.

_BACKEND_JD = """Senior Backend Engineer
Responsibilities
- Design and operate distributed backend services at high throughput
- Own service reliability, on-call rotation and incident response
- Build event-driven pipelines and evolve our microservice architecture
Requirements
- 7+ years building backend systems in production
- Deep experience with distributed systems and cloud infrastructure
- Strong grounding in API design and data modelling
Preferred
- Kubernetes exposure
"""

_FRONTEND_JD = """Software Engineer, Frontend
Responsibilities
- Build responsive user interfaces and design systems
- Work in React and TypeScript across our web application
Requirements
- Strong React and TypeScript
- Familiarity with CI/CD and automated testing
- Comfortable with modern build tooling
"""

_SHORT_JD = """Software Engineer
We are hiring an engineer. You should be able to write code and work in a team.
Requirements
- Programming experience
"""

_K8S_PRO_JD = """Senior Platform Engineer
Requirements
- Years of production Kubernetes ownership, running clusters at scale
- Terraform and infrastructure as code
- Platform engineering for internal developer teams
"""

ADVERSARIAL: list[Pair] = [
    Pair(id="adv-backend", company="Synthetic", title="Senior Backend Engineer",
         description=_BACKEND_JD, label=APPLY, needs_human=False, label_source="designed",
         reason="core domain: distributed backend, on-call, event-driven",
         tags=["role-shape"]),
    Pair(id="adv-frontend-generic", company="Synthetic", title="Software Engineer, Frontend",
         description=_FRONTEND_JD, label=SKIP, needs_human=False, label_source="designed",
         reason="generic React/TS/CI-CD requirements must not outrank a backend role",
         tags=["role-shape", "generic-boilerplate"]),
    Pair(id="adv-short-vague", company="Synthetic", title="Software Engineer",
         description=_SHORT_JD, label=REVIEW, needs_human=False, label_source="designed",
         reason="a short JD must not score high merely by asking for little",
         tags=["few-requirements"]),
    Pair(id="adv-k8s-professional", company="Synthetic", title="Senior Platform Engineer",
         description=_K8S_PRO_JD, label=REVIEW, needs_human=False, label_source="designed",
         reason="Kubernetes is side-project only; must not read as production ownership",
         tags=["evidence-tier"]),
]


def adversarial_assertions() -> list[dict[str, Any]]:
    """Orderings any acceptable scorer must produce, independent of scale."""
    return [
        {
            "name": "backend beats generic frontend",
            "higher": "adv-backend", "lower": "adv-frontend-generic",
            "why": "the measured failure: boilerplate frontend requirements scored "
                   "100% while a backend role scored 61.9%",
        },
        {
            "name": "backend beats a vague short posting",
            "higher": "adv-backend", "lower": "adv-short-vague",
            "why": "few requirements must not mean an easy high score",
        },
        {
            "name": "professional backend beats side-project Kubernetes",
            "higher": "adv-backend", "lower": "adv-k8s-professional",
            "why": "a side-project mention must not equal production ownership",
        },
    ]
