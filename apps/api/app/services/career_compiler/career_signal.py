"""Career signal: how much a project says about the candidate when no requirement of this job asks for it.

Used only after direct JD coverage is planned, to spend the page space that is left on the strongest unused,
supported evidence instead of leaving it empty. Deterministic and generic: it reads evidence types, tags, claim
text, project technologies and employment dates from career.json, never project names."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from app.services.career_compiler.store import PERSONAL_EMPLOYMENT_ID, CareerStore

#: Capability -> terms found in tags, technologies or claims. FUTURE capabilities are the 2026 market's priorities.
CAPABILITIES: dict[str, tuple[str, ...]] = {
    "agentic_ai": ("agentic", "agentic-ai", "agent", "agents", "mcp", "llm", "llms", "genai", "copilot", "prompt"),
    "ai_infrastructure": ("inference", "model serving", "gpu", "ml", "machine learning", "embedding", "embeddings",
                          "vector", "ai-governance", "ai-security", "evaluation"),
    "rag": ("rag", "retrieval", "semantic search", "hybrid search", "chunking", "reranking"),
    "developer_productivity": ("developer-productivity", "developer productivity", "cicd", "ci/cd", "tooling",
                               "debugging", "testing", "build", "deployment"),
    "distributed_systems": ("distributed-systems", "distributed", "microservices", "event-driven", "kafka", "queue",
                            "fault-isolation", "idempotency", "scalability", "consistency"),
    "platform_cloud": ("platform", "azure", "aws", "gcp", "cloud", "kubernetes", "docker", "serverless", "iac",
                       "sovereign-cloud", "terraform"),
    "security": ("security", "compliance", "policy", "risk", "safety"),
    "reliability": ("reliability", "observability", "latency", "incident", "operations", "dr", "availability"),
    "data": ("pipeline", "backfill", "etl", "analytics", "data"),
    "cost": ("cost", "savings", "efficiency"),
}
FUTURE = frozenset({"agentic_ai", "ai_infrastructure", "rag", "developer_productivity", "distributed_systems", "platform_cloud"})
IMPACT_TAGS = frozenset({"business-impact", "customer-impact", "org-impact", "cost"})
DEPTH_TYPES = frozenset({"architecture", "decision", "ownership", "reliability", "incident", "constraint"})
DEPTH_TAGS = frozenset({"distributed-systems", "fault-isolation", "idempotency", "api-design", "scalability"})
_IMPACT = re.compile(r"\d+(\.\d+)?\s*(%|x\b|×)|\$\s?\d|\b(cut|reduced|saved|increased|improved)\b.*\d", re.I)
_SCALE = re.compile(r"\b\d{1,3}(,\d{3})+\b|\b\d+(\.\d+)?\s*(k|m|b|million|billion|thousand)\b\+?|\b\d+k\+|\b(tb|pb|qps|rps)\b", re.I)
#: Weights: modern relevance first, then measured impact, scale, depth and recency.
W_FUTURE, W_IMPACT, W_SCALE, W_DEPTH, W_RECENCY = 1.5, 1.0, .8, .5, .6


@dataclass(frozen=True)
class CareerSignal:
    score: float
    capabilities: frozenset[str] = frozenset()
    reasons: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = field(default=())

    @property
    def supported(self) -> bool:
        return bool(self.evidence_ids)


def _has(text: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


def _month(value: str) -> int:
    match = re.match(r"(\d{4})-(\d{2})", value or "")
    return int(match[1]) * 12 + int(match[2]) - 1 if match else 0


def _recency(store: CareerStore, employment_id: str) -> float:
    """1.0 for the latest role, minus 0.125 per year before it. Measured against career.json, not the clock."""
    ends = {k: _month(str(v.get("end") or v.get("start") or "")) for k, v in store.employment.items()}
    latest = max(ends.values(), default=0)
    if employment_id == PERSONAL_EMPLOYMENT_ID or employment_id not in ends or not latest:
        return .7
    return max(0.0, 1 - (latest - ends[employment_id]) / 96)


def career_signal(store: CareerStore, project_id: str, evidence_ids: Iterable[str] | None = None) -> CareerSignal:
    """Score a project's supported evidence (optionally only `evidence_ids`). Unsupported evidence counts for nothing."""
    project = store.projects[project_id]
    wanted = set(evidence_ids) if evidence_ids is not None else None
    records = [e for e in store.project_evidence(project_id) if e.usable and (wanted is None or e.id in wanted)]
    if not records:
        return CareerSignal(0.0)
    tags = {t.lower() for e in records for t in e.tags}
    text = " ".join([*(e.claim.lower() for e in records), *tags, *(t.lower() for t in project.technologies)])
    capabilities = frozenset(c for c, terms in CAPABILITIES.items() if any(_has(text, t) for t in terms))
    future = min(len(capabilities & FUTURE), 3) / 3
    impact = float(any(e.type == "metric" or _IMPACT.search(e.claim) for e in records) or bool(tags & IMPACT_TAGS))
    scale = float(any(e.type == "scale" or _SCALE.search(e.claim) for e in records) or "scale" in tags)
    depth = float(bool({e.type for e in records} & DEPTH_TYPES) or bool(tags & DEPTH_TAGS))
    recency = _recency(store, project.employment_id)
    score = W_FUTURE * future + W_IMPACT * impact + W_SCALE * scale + W_DEPTH * depth + W_RECENCY * recency
    reasons = tuple(label for label, on in (
        (", ".join(sorted(c.replace("_", " ") for c in capabilities & FUTURE)), future > 0),
        ("measured impact", impact), ("scale", scale), ("technical depth", depth)) if on)
    ranked = sorted(records, key=lambda e: (e.type not in ("metric", "scale"), e.id))
    return CareerSignal(round(score, 3), capabilities, reasons, tuple(e.id for e in ranked))
