"""Stage 15-16: capture what the user accepts or rejects, and reuse it as style guidance. No RL, no fine-tuning.

Records are append-only JSONL. They never touch career.json and are never treated as evidence: a preference example
teaches DeepSeek how the user likes things phrased, and the validator still rejects any fact it carries over.
Each record with a replacement is a ready (prompt, chosen, rejected) triple for later preference training.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.services.career_compiler.jobs import data_root
from app.services.career_compiler.models import JobDescription
from app.services.career_compiler.store import mentions, tokens

Action = Literal["accept", "lock", "reject", "rewrite", "swap_evidence", "exclude"]
Reason = Literal["too_ai_sounding", "too_long", "too_vague", "too_many_buzzwords", "wrong_emphasis", "repetitive",
                 "metric_unnecessary", "too_technical", "not_technical_enough", "prefer_other_project", "other"]
#: Rejections for these reasons are about *what* was said, so the evidence is withheld for that job on regeneration.
CONTENT_REASONS = {"wrong_emphasis", "prefer_other_project"}
POSITIVE = {"accept", "lock"}
_lock = threading.Lock()


class FeedbackRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"fb_{uuid4().hex[:12]}")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    action: Action
    reason: Reason | None = None
    note: str = Field(default="", max_length=500)
    jd_id: str = ""
    jd_title: str = ""
    jd_company: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    resume_id: str = ""
    bullet_id: str = ""
    project_id: str = ""
    company: str = ""
    bullet_text: str = Field(default="", max_length=1200)
    evidence_ids: list[str] = Field(default_factory=list)
    replacement_text: str = Field(default="", max_length=1200)
    replacement_evidence_ids: list[str] = Field(default_factory=list)
    prompt_version: str = ""
    model: str = ""
    retrieval_version: str = ""


def _path() -> Path:
    return data_root() / "feedback" / "feedback.jsonl"


def record(item: FeedbackRecord) -> FeedbackRecord:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock, path.open("a", encoding="utf-8") as handle:
        handle.write(item.model_dump_json() + "\n")
    return item


def load(jd_id: str | None = None) -> list[FeedbackRecord]:
    path = _path()
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = FeedbackRecord.model_validate_json(line)
            if jd_id is None or item.jd_id == jd_id:
                out.append(item)
    return out


def excluded_evidence(jd_id: str) -> set[str]:
    """Evidence the user removed for this job. The latest decision per evidence id wins, so a later accept or
    lock brings it back."""
    excluded: set[str] = set()
    for item in load(jd_id):
        if item.action == "exclude" or (item.action == "reject" and item.reason in CONTENT_REASONS):
            excluded |= set(item.evidence_ids)
        elif item.action == "swap_evidence":
            excluded |= set(item.evidence_ids) - set(item.replacement_evidence_ids)
            excluded -= set(item.replacement_evidence_ids)
        elif item.action in POSITIVE:
            excluded -= set(item.evidence_ids)
    return excluded


def stats(jd_id: str | None = None) -> dict:
    items = load(jd_id)
    counts = {a: sum(1 for i in items if i.action == a) for a in Action.__args__}  # type: ignore[attr-defined]
    decided = sum(counts.values())
    positive = counts["accept"] + counts["lock"]
    return {"counts": counts, "decisions": decided,
            "acceptance_rate": round(positive / decided, 3) if decided else None,
            "rejection_rate": round((counts["reject"] + counts["exclude"]) / decided, 3) if decided else None}


def preference_examples(jd: JobDescription, project_ids: list[str], limit: int = 4) -> list[dict]:
    """Past REJECTED -> Reason -> PREFERRED examples most relevant to this job, for style only."""
    wanted = {s for r in jd.requirements for s in r.skills}
    words = {w for r in jd.requirements for w in tokens(r.normalized_requirement)}
    projects = set(project_ids)
    scored = []
    for n, item in enumerate(load()):
        if item.action in ("reject", "rewrite") and item.reason and item.bullet_text:
            kind = "correction"
        elif item.action in POSITIVE and item.bullet_text:
            kind = "accepted"
        else:
            continue
        relevance = (3 if item.project_id in projects else 0) + min(2, sum(mentions(item.bullet_text, s) for s in wanted))
        relevance += min(1.0, len(tokens(item.bullet_text) & words) / 10)
        relevance += 1 if item.replacement_text else 0
        scored.append((relevance, n, kind, item))
    scored.sort(key=lambda s: (-s[0], -s[1]))
    out, seen = [], set()
    for _, _, kind, item in scored:
        key = item.bullet_text.casefold()
        if key in seen:
            continue
        seen.add(key)
        if kind == "correction":
            out.append({"rejected": item.bullet_text, "reason": item.reason, "preferred": item.replacement_text or None})
        elif sum(1 for o in out if "accepted" in o) < 2:
            out.append({"accepted": item.bullet_text})
        if len(out) >= limit:
            break
    return out


def preference_pairs() -> list[dict]:
    """(prompt, chosen, rejected) triples for a future preference-training run. Nothing trains on them today."""
    return [{"id": i.id, "prompt": {"jd_id": i.jd_id, "requirement_ids": i.requirement_ids, "evidence_ids": i.evidence_ids,
                                    "project_id": i.project_id},
             "chosen": i.replacement_text, "rejected": i.bullet_text, "reason": i.reason, "model": i.model,
             "prompt_version": i.prompt_version}
            for i in load() if i.action in ("reject", "rewrite") and i.replacement_text and i.bullet_text]
