"""Lightweight neural scorers: MiniLM bi-encoder and cross-encoder.

Kept apart from `approaches.py` so the dependency-free experiments can be run
and reasoned about without torch installed, and so importing the bench never
drags a 200MB model into memory by accident.

Two things are tested for each model, because the interesting question is not
"does semantics help" but *where* it helps:

    whole-document   one embedding of the posting against one of the resume
    evidence matrix  every requirement against every piece of resume evidence,
                     keeping the best supporting evidence for each requirement

The evidence matrix is the more useful object regardless of which scores
better. It says *which* resume bullet supports *which* requirement, and whether
that support is professional or side-project - which is what a later, safe
resume-tailoring step needs, and what a single similarity number can never
provide.

Everything runs on CPU by design: the GPU is 8GB and is wanted for Ollama, and
these models are small enough that CPU inference is milliseconds.
"""

from __future__ import annotations

import gc
import os
import time
from dataclasses import dataclass, field
from typing import Any

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# Keep thread counts modest: this shares a laptop with everything else, and
# oversubscribing cores makes latency less predictable, not better.
os.environ.setdefault("OMP_NUM_THREADS", "4")

from .dataset import Pair  # noqa: E402
from .structure import Evidence, parse_job  # noqa: E402

BI_ENCODER = "sentence-transformers/all-MiniLM-L6-v2"
CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L6-v2"
BGE_RERANKER = "BAAI/bge-reranker-v2-m3"

_loaded: dict[str, Any] = {}


def load_bi_encoder(name: str = BI_ENCODER):
    if name not in _loaded:
        from sentence_transformers import SentenceTransformer

        _loaded[name] = SentenceTransformer(name, device="cpu")
    return _loaded[name]


def load_cross_encoder(name: str = CROSS_ENCODER):
    if name not in _loaded:
        from sentence_transformers import CrossEncoder

        _loaded[name] = CrossEncoder(name, device="cpu", max_length=512)
    return _loaded[name]


def unload_all() -> None:
    """Drop every model. Only one should ever be resident on this machine."""
    _loaded.clear()
    gc.collect()


# ---------------------------------------------------------------------------
# Evidence matrix
# ---------------------------------------------------------------------------

@dataclass
class RequirementMatch:
    requirement: str
    importance: float          # 1.0 must-have, lower for preferred
    best_evidence: str
    evidence_source: str       # professional | project | skills | none
    score: float               # 0..1 semantic similarity

    @property
    def is_supported(self) -> bool:
        return self.score >= 0.35 and self.evidence_source != "none"


@dataclass
class EvidenceMatrix:
    matches: list[RequirementMatch] = field(default_factory=list)

    def aggregate(self, tiers: dict[str, float]) -> dict[str, float]:
        """Roll the matrix up into the few numbers a gate can use."""
        if not self.matches:
            return {"weighted": 0.0, "professionalRatio": 0.0,
                    "projectOnlyRatio": 0.0, "missingCritical": 0.0}
        weighted_total = sum(m.importance for m in self.matches)
        weighted_hit = sum(
            m.importance * m.score * tiers.get(m.evidence_source, 0.0)
            for m in self.matches
        )
        supported = [m for m in self.matches if m.is_supported]
        professional = [m for m in supported if m.evidence_source == "professional"]
        project_only = [m for m in supported if m.evidence_source == "project"]
        critical_missing = [
            m for m in self.matches if m.importance >= 1.0 and not m.is_supported
        ]
        return {
            "weighted": weighted_hit / weighted_total if weighted_total else 0.0,
            "professionalRatio": len(professional) / len(self.matches),
            "projectOnlyRatio": len(project_only) / len(self.matches),
            # Counted, not ratioed: one genuinely critical gap should matter
            # more than several optional ones, which a ratio would dilute.
            "missingCritical": float(len(critical_missing)),
        }

    def to_rows(self, limit: int = 12) -> list[dict[str, Any]]:
        ranked = sorted(self.matches, key=lambda m: (-m.importance, -m.score))
        return [
            {
                "requirement": m.requirement[:110],
                "importance": round(m.importance, 2),
                "evidence": m.best_evidence[:90],
                "source": m.evidence_source,
                "score": round(m.score, 3),
            }
            for m in ranked[:limit]
        ]


def _requirements(pair: Pair, cap: int = 14) -> list[tuple[str, float]]:
    """Requirements with importance. Must-haves outrank preferred."""
    job = parse_job(pair.title, pair.company, pair.description)
    items = [(r, 1.0) for r in job.must_have[:cap]]
    items += [(r, 0.4) for r in job.preferred[: cap // 2]]
    if not items:
        items = [(r, 1.0) for r in job.responsibilities[:cap]]
    return items


def build_evidence_matrix_bi(pair: Pair, ctx, model) -> EvidenceMatrix:
    """Bi-encoder: embed once, compare by cosine. Cheap and batchable."""
    from sentence_transformers import util

    requirements = _requirements(pair)
    if not requirements:
        return EvidenceMatrix()

    evidence: list[Evidence] = ctx.resume.all_evidence
    if not evidence:
        return EvidenceMatrix()

    if "_evidence_emb" not in ctx.cache:
        ctx.cache["_evidence_emb"] = model.encode(
            [e.text for e in evidence], convert_to_tensor=True,
            normalize_embeddings=True, show_progress_bar=False,
        )
    evidence_emb = ctx.cache["_evidence_emb"]

    req_emb = model.encode(
        [r for r, _ in requirements], convert_to_tensor=True,
        normalize_embeddings=True, show_progress_bar=False,
    )
    similarity = util.cos_sim(req_emb, evidence_emb)

    matrix = EvidenceMatrix()
    for index, (requirement, importance) in enumerate(requirements):
        row = similarity[index]
        best = int(row.argmax())
        score = float(row[best])
        item = evidence[best]
        matrix.matches.append(RequirementMatch(
            requirement=requirement, importance=importance,
            best_evidence=item.text, evidence_source=item.source if score >= 0.35 else "none",
            score=max(0.0, score),
        ))
    return matrix


def build_evidence_matrix_cross(pair: Pair, ctx, model, top_k: int = 8) -> EvidenceMatrix:
    """Cross-encoder: score each requirement against each candidate evidence.

    Quadratic, so the evidence set is pre-narrowed by cheap lexical overlap
    before the model sees it. Scoring 14 requirements against 60 stories would
    be 840 forward passes per job; against the 8 most plausible it is 112.
    """
    requirements = _requirements(pair)
    evidence: list[Evidence] = ctx.resume.all_evidence
    if not requirements or not evidence:
        return EvidenceMatrix()

    from .approaches import tokenize

    evidence_tokens = [set(tokenize(e.text)) for e in evidence]

    pairs_to_score: list[tuple[str, str]] = []
    index_map: list[tuple[int, int]] = []
    for r_index, (requirement, _) in enumerate(requirements):
        wanted = set(tokenize(requirement))
        ranked = sorted(
            range(len(evidence)),
            key=lambda e_index: -len(wanted & evidence_tokens[e_index]),
        )[:top_k]
        for e_index in ranked:
            pairs_to_score.append((requirement, evidence[e_index].text))
            index_map.append((r_index, e_index))

    raw = model.predict(pairs_to_score, show_progress_bar=False, batch_size=32)

    best: dict[int, tuple[float, int]] = {}
    for (r_index, e_index), value in zip(index_map, raw):
        score = float(value)
        if r_index not in best or score > best[r_index][0]:
            best[r_index] = (score, e_index)

    matrix = EvidenceMatrix()
    for r_index, (requirement, importance) in enumerate(requirements):
        score, e_index = best.get(r_index, (0.0, 0))
        # ms-marco cross-encoders emit unbounded logits; squash to 0..1 so the
        # aggregate is comparable with the bi-encoder's cosine.
        normalized = 1.0 / (1.0 + pow(2.718281828, -score))
        item = evidence[e_index]
        matrix.matches.append(RequirementMatch(
            requirement=requirement, importance=importance,
            best_evidence=item.text,
            evidence_source=item.source if normalized >= 0.35 else "none",
            score=normalized,
        ))
    return matrix


# ---------------------------------------------------------------------------
# Scorers
# ---------------------------------------------------------------------------

def score_minilm_whole(pair: Pair, ctx) -> float:
    """Experiment 6A: one embedding each side."""
    from sentence_transformers import util

    model = load_bi_encoder()
    if "_resume_emb" not in ctx.cache:
        ctx.cache["_resume_emb"] = model.encode(
            ctx.resume_text[:8000], convert_to_tensor=True,
            normalize_embeddings=True, show_progress_bar=False,
        )
    job_emb = model.encode(
        f"{pair.title}\n{pair.description}"[:8000], convert_to_tensor=True,
        normalize_embeddings=True, show_progress_bar=False,
    )
    return 100.0 * max(0.0, float(util.cos_sim(job_emb, ctx.cache["_resume_emb"])[0][0]))


def score_minilm_evidence(pair: Pair, ctx) -> float:
    """Experiment 6B: requirement-level evidence matching."""
    model = load_bi_encoder()
    matrix = build_evidence_matrix_bi(pair, ctx, model)
    parts = matrix.aggregate(ctx.tiers)
    return 100.0 * parts["weighted"]


def score_cross_evidence(pair: Pair, ctx) -> float:
    """Experiment 7: cross-encoder over requirement/evidence pairs."""
    model = load_cross_encoder()
    matrix = build_evidence_matrix_cross(pair, ctx, model)
    parts = matrix.aggregate(ctx.tiers)
    return 100.0 * parts["weighted"]


def score_cross_whole(pair: Pair, ctx) -> float:
    model = load_cross_encoder()
    raw = float(model.predict(
        [(f"{pair.title}. {pair.description[:2000]}", ctx.resume_text[:2000])],
        show_progress_bar=False,
    )[0])
    return 100.0 / (1.0 + pow(2.718281828, -raw))


NEURAL_APPROACHES = {
    "minilm-whole": score_minilm_whole,
    "minilm-evidence": score_minilm_evidence,
    "cross-whole": score_cross_whole,
    "cross-evidence": score_cross_evidence,
}


def model_footprint(name: str) -> dict[str, Any]:
    """On-disk size of a cached model, for the cost column of the leaderboard."""
    from pathlib import Path

    home = Path.home() / ".cache" / "huggingface" / "hub"
    slug = "models--" + name.replace("/", "--")
    target = home / slug
    if not target.exists():
        return {}
    total = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    return {"modelMb": round(total / 1e6, 1)}
