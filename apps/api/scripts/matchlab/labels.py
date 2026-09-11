"""Four independent label sources, and the rules for combining them.

    human            a person decided. Always wins.
    teacher          Gemini, judging the body with the title hidden.
    deterministic    body-only role shape, seniority, lexical relevance,
                     hard eligibility - no model of any kind.
    weak_consensus   teacher and deterministic agree. Only then.
    uncertain        they disagree. Recorded as uncertain rather than resolved.

The point of keeping these apart is that combining them silently is how a
benchmark starts grading a scorer against its own assumptions. Bootstrap labels
came from job titles and the winning scorer read job titles, which inflated its
AUC from roughly 0.82 to 0.945. Teacher labels are title-blind, so a body-only
scorer measured against them is being asked a real question.

`uncertain` is a first-class outcome, not a failure. Forcing a label where two
independent judges disagree manufactures agreement that does not exist, and the
disagreements are the most informative rows in the set.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .dataset import APPLY, REVIEW, SKIP, Pair, load_human_labels

API_ROOT = Path(__file__).resolve().parents[2]
TEACHER_LABELS = API_ROOT / "data" / "matchlab_teacher_labels.json"

SOURCES = ("human", "weak_consensus", "teacher", "deterministic", "bootstrap")

NAMES = {APPLY: "APPLY", REVIEW: "REVIEW", SKIP: "SKIP"}


@dataclass
class LabelSet:
    """One source's opinion about every posting."""

    source: str
    labels: dict[str, int] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    uncertain: set[str] = field(default_factory=set)

    def label_for(self, pair_id: str) -> int | None:
        return self.labels.get(pair_id)

    def binary_for(self, pair_id: str) -> int | None:
        """APPLY vs SKIP. REVIEW and unknown are excluded from gate metrics."""
        value = self.labels.get(pair_id)
        if value is None or value == REVIEW:
            return None
        return int(value == APPLY)

    def counts(self) -> dict[str, int]:
        out = {"APPLY": 0, "REVIEW": 0, "SKIP": 0}
        for value in self.labels.values():
            out[NAMES[value]] += 1
        out["UNCERTAIN"] = len(self.uncertain)
        return out


# ---------------------------------------------------------------------------
# Deterministic opinion - no model, body only
# ---------------------------------------------------------------------------

#: Derived from the body-only score distribution rather than guessed. Postings
#: between these bands are genuinely ambiguous to a lexical scorer, and saying
#: so is more useful than forcing them either way.
# Calibrated to the measured body-only distribution over the evaluation set
# (min 26.9, p25 41.2, median 45.0, p75 49.9, max 76.0) rather than guessed.
# The earlier 62/42 pair put only 4 postings above the apply line, which is not
# an opinion so much as an abstention.
DET_APPLY_AT = 50.0
DET_SKIP_BELOW = 41.0


def deterministic_opinion(pair: Pair, ctx) -> tuple[int, str]:
    """A judgement from deterministic signals only, with the title withheld.

    Withholding the title matters here for the same reason it does for the
    teacher: a deterministic signal that reads the title would agree with a
    title-derived bootstrap label for the wrong reason, and consensus between
    two title-readers is not independent evidence.
    """
    from . import approaches as A
    from .structure import parse_job

    blind = Pair(
        id=pair.id, company=pair.company, title="Software Engineer",
        description=pair.description, label=pair.label,
    )

    job = parse_job(blind.title, blind.company, blind.description)
    parts = A.role_shape_components(blind, ctx)
    score = A.score_role_shape(blind, ctx)

    hard = _hard_constraint(pair)
    if hard:
        return SKIP, hard

    if score >= DET_APPLY_AT:
        return APPLY, f"body-only role shape {score:.0f} (family={job.role_family or '?'})"
    if score < DET_SKIP_BELOW:
        return SKIP, f"body-only role shape {score:.0f} (family={job.role_family or '?'})"
    return REVIEW, f"body-only role shape {score:.0f}, inconclusive"


#: Rejections from the production filter that say nothing about whether the
#: candidate could do the job. The bench constructs job dicts from the
#: evaluation set rather than from live queue rows, so they lack fields the
#: production filter checks for operational reasons.
#:
#: This mattered: without the exclusion, "Posting has no application URL"
#: vetoed all 90 postings, the deterministic source labelled everything SKIP,
#: and the consensus set was silently meaningless.
_NOT_ELIGIBILITY = (
    "application url", "no url", "already", "duplicate", "posted", "stale",
    "expired", "too old", "missing",
)


def _hard_constraint(pair: Pair) -> str | None:
    """Eligibility facts, not opinions. These veto regardless of fit.

    Only genuine eligibility: citizenship or ITAR restrictions, a location the
    candidate cannot work in, a role that is not software engineering. Data
    completeness is not eligibility.
    """
    try:
        from app.db.store import get_kv, session_scope
        from app.services.application_assistant.job_filter_ranker import (
            evaluate_hard_filters,
        )

        with session_scope() as db:
            profile = get_kv(db, "profile") or {}
        passed, reason = evaluate_hard_filters(
            {"company": pair.company, "title": pair.title,
             "description": pair.description, "id": pair.id,
             "applicationUrl": f"https://example.invalid/{pair.id}"},
            profile, [],
        )
        if passed:
            return None
        text = str(reason).lower()
        if any(marker in text for marker in _NOT_ELIGIBILITY):
            return None
        return str(reason)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Building each source
# ---------------------------------------------------------------------------

def bootstrap_set(pairs: list[Pair]) -> LabelSet:
    labels = LabelSet(source="bootstrap")
    for pair in pairs:
        if pair.label is not None:
            labels.labels[pair.id] = pair.label
            labels.reasons[pair.id] = pair.reason
    return labels


def human_set(pairs: list[Pair]) -> LabelSet:
    stored = load_human_labels()
    labels = LabelSet(source="human")
    for pair in pairs:
        record = stored.get(pair.id)
        if record:
            labels.labels[pair.id] = int(record["label"])
            labels.reasons[pair.id] = record.get("reason", "")
    return labels


def load_teacher_set(pairs: list[Pair]) -> LabelSet:
    labels = LabelSet(source="teacher")
    try:
        stored = json.loads(TEACHER_LABELS.read_text(encoding="utf-8"))
    except Exception:
        return labels
    for pair in pairs:
        record = stored.get(pair.id)
        if not record:
            continue
        labels.labels[pair.id] = {"APPLY": APPLY, "REVIEW": REVIEW,
                                  "SKIP": SKIP}[record["decision"]]
        labels.reasons[pair.id] = record.get("reason", "")
    return labels


def deterministic_set(pairs: list[Pair], ctx) -> LabelSet:
    labels = LabelSet(source="deterministic")
    for pair in pairs:
        value, reason = deterministic_opinion(pair, ctx)
        labels.labels[pair.id] = value
        labels.reasons[pair.id] = reason
    return labels


#: Teacher confidence below this is not strong enough to anchor a consensus
#: label, however well the deterministic side agrees.
MIN_TEACHER_CONFIDENCE = 0.6


def consensus_set(
    pairs: list[Pair],
    teacher: LabelSet,
    deterministic: LabelSet,
    teacher_records: dict[str, Any] | None = None,
) -> LabelSet:
    """Label only where two independent judges agree. Otherwise, uncertain."""
    records = teacher_records or {}
    labels = LabelSet(source="weak_consensus")
    for pair in pairs:
        t = teacher.label_for(pair.id)
        d = deterministic.label_for(pair.id)
        if t is None or d is None:
            continue
        confidence = float((records.get(pair.id) or {}).get("confidence") or 1.0)

        if t == d and confidence >= MIN_TEACHER_CONFIDENCE:
            labels.labels[pair.id] = t
            labels.reasons[pair.id] = (
                f"agreed ({NAMES[t]}); teacher conf {confidence:.2f}"
            )
            continue

        # APPLY against SKIP is a real contradiction. APPLY against REVIEW is
        # only a difference of confidence, so it settles at REVIEW rather than
        # being thrown away.
        if {t, d} == {APPLY, SKIP} or confidence < MIN_TEACHER_CONFIDENCE:
            labels.uncertain.add(pair.id)
            labels.reasons[pair.id] = (
                f"teacher={NAMES[t]} deterministic={NAMES[d]} "
                f"conf={confidence:.2f}"
            )
        else:
            labels.labels[pair.id] = REVIEW
            labels.reasons[pair.id] = (
                f"partial ({NAMES[t]} vs {NAMES[d]}) -> REVIEW"
            )
    return labels


def with_human_override(base: LabelSet, human: LabelSet) -> LabelSet:
    """Human labels win over everything, always."""
    merged = LabelSet(
        source=f"{base.source}+human",
        labels=dict(base.labels), reasons=dict(base.reasons),
        uncertain=set(base.uncertain),
    )
    for pair_id, value in human.labels.items():
        merged.labels[pair_id] = value
        merged.reasons[pair_id] = f"human: {human.reasons.get(pair_id, '')}"
        merged.uncertain.discard(pair_id)
    return merged


# ---------------------------------------------------------------------------

def agreement(a: LabelSet, b: LabelSet) -> dict[str, Any]:
    """How two sources compare where both expressed an opinion."""
    shared = set(a.labels) & set(b.labels)
    if not shared:
        return {"a": a.source, "b": b.source, "shared": 0}
    same = sum(1 for i in shared if a.labels[i] == b.labels[i])
    matrix: dict[str, int] = {}
    for pair_id in shared:
        key = f"{NAMES[a.labels[pair_id]]}->{NAMES[b.labels[pair_id]]}"
        matrix[key] = matrix.get(key, 0) + 1
    # Agreement on the decision that matters: would both auto-apply?
    apply_a = {i for i in shared if a.labels[i] == APPLY}
    apply_b = {i for i in shared if b.labels[i] == APPLY}
    union = apply_a | apply_b
    return {
        "a": a.source, "b": b.source, "shared": len(shared),
        "agreement": round(same / len(shared), 3),
        "applyJaccard": round(len(apply_a & apply_b) / len(union), 3) if union else None,
        "confusion": dict(sorted(matrix.items(), key=lambda kv: -kv[1])),
    }
