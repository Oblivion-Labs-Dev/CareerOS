"""Gemini as an offline labelling teacher. No local model is loaded, ever.

This exists to break a circularity. Bootstrap labels were derived from job
titles, and the winning scorer reads job titles, so its 0.945 AUC was partly
reconstructing the labeller - measured: title-only scored 0.978, *higher* than
title+body, which only happens when the label is a function of the title.

So the teacher never sees a title. The title field is not sent, and any
occurrence of it inside the body is redacted before the request is built. What
comes back is therefore a judgement about the described work, and a body-only
scorer evaluated against these labels is not being graded on its ability to
guess a title.

Three rules this module holds to:

* **Nothing local runs.** No Ollama, no sentence-transformers, no torch. The
  only compute is an HTTPS request.
* **Deterministic where the API allows it.** Temperature 0 and a strict JSON
  schema, so the same posting produces the same judgement.
* **Cached permanently.** Keyed by the content actually sent, so re-running the
  bench costs nothing and a changed prompt invalidates cleanly rather than
  silently reusing answers to a different question.

The teacher's judgement is a *label for evaluation*. It is never a CareerOS
production score, and it is never a human label.

## Why the HTTP no longer lives here

It used to. This module had its own throttle, its own retry loop and its own
sense of when to give up, and so did every other thing in CareerOS that wanted
to call Gemini. That is how a batch of 140 postings ends up competing with a
live application for the same rate limit. All of it now goes through
`app.services.gemini.gateway`, at the lowest priority in the queue, so a
labelling run yields to anything a person is waiting on and can never be the
reason an application went unanswered.

The module keeps its own cache directory as well as the gateway's, because the
87 labels produced before the move live there and must not be re-charged.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = API_ROOT / "data" / "matchlab_teacher_cache"

if str(API_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(API_ROOT))

from app.services.gemini import config as gemini_config  # noqa: E402
from app.services.gemini import enrichment  # noqa: E402
from app.services.gemini import schemas as gemini_schemas  # noqa: E402
from app.services.gemini.title_redaction import strip_title  # noqa: F401,E402

MODEL = os.environ.get("MATCHLAB_TEACHER_MODEL", gemini_config.MODEL)

#: Part of the legacy cache key. Kept in step with the shared schema version so
#: the two cache layers invalidate together rather than one silently serving
#: answers to a question the other has stopped asking.
PROMPT_VERSION = gemini_schemas.TEACHER_VERSION

#: Shown in the study output so a reader knows results were cached, not re-judged.
TEACHER_CACHE_NOTE = (
    "Teacher responses are cached permanently by content hash; re-running the "
    "study makes no API calls unless a posting or the prompt changed."
)

ROLE_FAMILIES = gemini_schemas.ROLE_FAMILIES
SCHEMA = gemini_schemas.TEACHER_SCHEMA
SYSTEM = gemini_schemas.TEACHER_SYSTEM


@dataclass
class TeacherLabel:
    decision: str
    primary_role_family: str
    secondary_role_family: str
    seniority_match: bool
    critical_mismatch: bool
    confidence: float
    reason: str
    cached: bool = False
    latency_ms: float = 0.0

    @property
    def label(self) -> int:
        from matchlab.dataset import APPLY, REVIEW, SKIP

        return {"APPLY": APPLY, "REVIEW": REVIEW, "SKIP": SKIP}[self.decision]

    def to_dict(self) -> dict[str, Any]:
        return {
            # Never "human", and never bare "gemini". A reader of the labels
            # file has to be able to tell at a glance that a model produced
            # this, because human labels override automated ones everywhere
            # they both exist.
            "label_source": "gemini_teacher",
            "decision": self.decision,
            "primary_role_family": self.primary_role_family,
            "secondary_role_family": self.secondary_role_family,
            "seniority_match": self.seniority_match,
            "critical_mismatch": self.critical_mismatch,
            "confidence": self.confidence,
            "reason": self.reason,
        }


# ── legacy cache ─────────────────────────────────────────────────────────────

def _cache_key(resume: str, body: str) -> str:
    digest = hashlib.sha256()
    digest.update(PROMPT_VERSION.encode())
    digest.update(MODEL.encode())
    digest.update(resume.encode("utf-8", "ignore"))
    digest.update(body.encode("utf-8", "ignore"))
    return digest.hexdigest()[:32]


def _read_cache(key: str) -> dict[str, Any] | None:
    try:
        return json.loads((CACHE_DIR / f"{key}.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(key: str, payload: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")


def _from_cached(payload: dict[str, Any]) -> TeacherLabel:
    label = dict(payload.get("label") or {})
    label.pop("label_source", None)
    return TeacherLabel(**label, cached=True)


# ── judging ──────────────────────────────────────────────────────────────────

def judge(
    resume_summary: str,
    title: str,
    body: str,
    *,
    timeout: float = 60.0,
    allow_network: bool = True,
) -> TeacherLabel | None:
    """Label one posting. Cached; returns None only when the call fails.

    Synchronous, because the MatchLab scripts are. The gateway is async, so the
    call is driven on a private event loop - each script process gets its own
    gateway and the queue is only ever this one run's work.
    """
    redacted, redactions = strip_title(title, body)

    key = _cache_key(resume_summary[:6000], redacted[:9000])
    cached = _read_cache(key)
    if cached:
        return _from_cached(cached)
    if not allow_network:
        return None

    started = time.perf_counter()
    result = asyncio.run(
        enrichment.label_posting(resume_summary, title, body, strip_title=strip_title)
    )
    if not result.available:
        return None

    label = TeacherLabel(
        decision=result.decision,
        primary_role_family=result.primary_role_family or "other",
        secondary_role_family=result.secondary_role_family,
        seniority_match=result.seniority_match,
        critical_mismatch=result.critical_mismatch,
        confidence=result.confidence,
        reason=result.reason,
        cached=result.cached,
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    _write_cache(key, {
        "model": MODEL, "promptVersion": PROMPT_VERSION,
        "redactions": redactions, "label": label.to_dict(),
        "at": time.strftime("%Y-%m-%d %H:%M"),
    })
    return label


def build_resume_summary() -> str:
    """A compact, title-free description of the candidate for the teacher."""
    from app.db.store import get_kv, session_scope
    from app.services.application_assistant.candidate_match_context import (
        extract_resume_text,
    )

    with session_scope() as db:
        documents = get_kv(db, "documents") or {}
    return (extract_resume_text(documents) or "").strip()


# Kept so the module's own regex helpers remain importable by anything that
# reached into them before the redaction moved into `app`.
_NOISE = re.compile(
    r"\b(senior|staff|principal|lead|sr|junior|associate|"
    r"software|engineer|engineering|developer|i{1,3}|\d+)\b",
    re.I,
)
