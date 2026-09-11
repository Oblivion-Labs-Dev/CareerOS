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
production score.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

API_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = API_ROOT / "data" / "matchlab_teacher_cache"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
# gemini-flash-latest exhausted its free-tier daily quota part way through the
# first run; flash-lite has a separate, larger allowance and is ample for a
# labelling task with a fixed schema. Override with MATCHLAB_TEACHER_MODEL.
MODEL = os.environ.get("MATCHLAB_TEACHER_MODEL", "gemini-flash-lite-latest")

#: Bump when the prompt or schema changes. Part of the cache key, so old
#: answers to a different question are never silently reused.
PROMPT_VERSION = "v1"

#: Shown in the study output so a reader knows results were cached, not re-judged.
TEACHER_CACHE_NOTE = (
    "Teacher responses are cached permanently by content hash; re-running the "
    "study makes no API calls unless a posting or the prompt changed."
)

ROLE_FAMILIES = [
    "backend", "frontend", "platform", "infrastructure", "sre", "mobile",
    "data", "ml", "security", "fullstack", "embedded", "qa", "other",
]

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["APPLY", "REVIEW", "SKIP"]},
        "primary_role_family": {"type": "string", "enum": ROLE_FAMILIES},
        "secondary_role_family": {"type": "string", "enum": ROLE_FAMILIES + [""]},
        "seniority_match": {"type": "boolean"},
        "critical_mismatch": {"type": "boolean"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": [
        "decision", "primary_role_family", "secondary_role_family",
        "seniority_match", "critical_mismatch", "confidence", "reason",
    ],
}

SYSTEM = """You judge whether a candidate should apply to a job, from the job's
description only. You are never shown the job title; judge from the described work.

Return JSON only.

decision:
  APPLY  - the described work is the kind of engineering this candidate does, at a
           compatible level, with no requirement they plainly cannot meet
  REVIEW - plausible but uncertain, or the description is too vague to judge
  SKIP   - a different kind of engineering, an incompatible level, or a
           requirement the candidate clearly cannot meet

primary_role_family / secondary_role_family: the shape of the work described.
  Use secondary when the job genuinely spans two, otherwise "".

seniority_match: does the described level fit a senior engineer with ~9 years?
critical_mismatch: is there a must-have requirement the candidate cannot evidence?
confidence: 0..1, how clearly the description supports your decision. Low when
  the posting is short, generic, or does not describe the work.
reason: one sentence, factual, naming the deciding evidence.

Judge the work, not the writing. A vague posting is REVIEW with low confidence,
not SKIP."""


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
            "decision": self.decision,
            "primary_role_family": self.primary_role_family,
            "secondary_role_family": self.secondary_role_family,
            "seniority_match": self.seniority_match,
            "critical_mismatch": self.critical_mismatch,
            "confidence": self.confidence,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Title removal
# ---------------------------------------------------------------------------

_NOISE = re.compile(r"\b(senior|staff|principal|lead|sr|junior|associate|"
                    r"software|engineer|engineering|developer|i{1,3}|\d+)\b", re.I)


def strip_title(title: str, body: str) -> tuple[str, int]:
    """Remove the job title from the body. Returns (redacted body, redactions).

    Postings almost always repeat the title as a heading or in the opening
    line, so omitting the title field alone would not hide it. Both the exact
    title and its distinctive part - the title with generic words like
    "Senior Software Engineer" removed - are redacted, because "Engine Systems"
    leaks the role family just as effectively as the full title does.
    """
    redacted = body
    count = 0

    targets = [title.strip()]
    distinctive = _NOISE.sub(" ", title)
    distinctive = re.sub(r"[^\w\s/&+-]", " ", distinctive)
    distinctive = re.sub(r"\s{2,}", " ", distinctive).strip(" ,-–—|/")
    if len(distinctive) >= 4:
        targets.append(distinctive)

    for target in targets:
        if len(target) < 4:
            continue
        pattern = re.compile(re.escape(target).replace(r"\ ", r"[\s\-]+"), re.I)
        redacted, hits = pattern.subn("[ROLE TITLE REDACTED]", redacted)
        count += hits

    # A leading line that is short and heading-like is the title even when the
    # strings did not match exactly.
    lines = redacted.splitlines()
    while lines and (not lines[0].strip() or (
        len(lines[0].strip()) < 70
        and not lines[0].strip().endswith((".", ":", ";"))
        and len(lines[0].split()) <= 9
        and "REDACTED" not in lines[0]
        and _looks_like_heading(lines[0])
    )):
        if lines[0].strip():
            count += 1
        lines.pop(0)
    return "\n".join(lines).strip(), count


def _looks_like_heading(line: str) -> bool:
    words = line.strip().split()
    if not words:
        return False
    capitalised = sum(1 for w in words if w[:1].isupper())
    return capitalised >= max(1, len(words) // 2)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_key(resume: str, body: str) -> str:
    digest = hashlib.sha256()
    digest.update(PROMPT_VERSION.encode())
    digest.update(MODEL.encode())
    digest.update(resume.encode("utf-8", "ignore"))
    digest.update(body.encode("utf-8", "ignore"))
    return digest.hexdigest()[:32]


def _read_cache(key: str) -> dict[str, Any] | None:
    path = CACHE_DIR / f"{key}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(key: str, payload: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(
        json.dumps(payload, indent=1), encoding="utf-8"
    )


# ---------------------------------------------------------------------------

def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    env = (API_ROOT / ".env").read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"^GEMINI_API_KEY=(.+)$", env, re.M)
    if not match or not match.group(1).strip():
        raise RuntimeError("GEMINI_API_KEY is not configured")
    return match.group(1).strip()


#: Gemini's free tier rate-limits aggressively and returns transient 503s under
#: load. Neither is a reason to lose a label, so calls are spaced and retried.
#: Measured: without this, roughly a third of a 140-posting run failed.
MIN_SECONDS_BETWEEN_CALLS = 2.5
MAX_ATTEMPTS = 5

_last_call_at = 0.0


def _throttle() -> None:
    global _last_call_at
    wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call_at)
    if wait > 0:
        time.sleep(wait)
    _last_call_at = time.monotonic()


def _extract_json(content: str) -> dict[str, Any] | None:
    """Parse the reply, tolerating a markdown fence or trailing prose.

    The schema is supposed to guarantee bare JSON and usually does, but a
    malformed reply should cost one retry rather than one lost label.
    """
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _call_with_retry(payload: dict[str, Any], timeout: float) -> dict[str, Any] | None:
    """One judgement, retried through rate limits and transient server errors."""
    delay = 5.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _throttle()
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    f"{BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {_api_key()}",
                             "Content-Type": "application/json"},
                    json=payload,
                )
            if response.status_code in (429, 500, 502, 503, 504):
                # Honour Retry-After when the server sends one; it knows better
                # than an exponential guess.
                hinted = response.headers.get("retry-after")
                wait = float(hinted) if (hinted or "").replace(".", "", 1).isdigit() else delay
                if attempt < MAX_ATTEMPTS:
                    print(f"      {response.status_code}; retrying in {wait:.0f}s "
                          f"({attempt}/{MAX_ATTEMPTS})", flush=True)
                    time.sleep(wait)
                    delay = min(delay * 2, 60.0)
                    continue
                print(f"      gave up after {MAX_ATTEMPTS} attempts "
                      f"({response.status_code})", flush=True)
                return None
            response.raise_for_status()
            parsed = _extract_json(response.json()["choices"][0]["message"]["content"])
            if parsed is not None:
                return parsed
            if attempt < MAX_ATTEMPTS:
                print(f"      unparseable reply; retrying ({attempt}/{MAX_ATTEMPTS})",
                      flush=True)
                continue
            return None
        except Exception as exc:  # noqa: BLE001
            if attempt < MAX_ATTEMPTS:
                print(f"      {type(exc).__name__}; retrying in {delay:.0f}s "
                      f"({attempt}/{MAX_ATTEMPTS})", flush=True)
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
                continue
            print(f"    teacher call failed: {type(exc).__name__}: {str(exc)[:110]}")
            return None
    return None


def judge(
    resume_summary: str,
    title: str,
    body: str,
    *,
    timeout: float = 60.0,
    allow_network: bool = True,
) -> TeacherLabel | None:
    """Label one posting. Cached; returns None only when the call fails."""
    redacted, redactions = strip_title(title, body)
    prompt = (
        "CANDIDATE\n"
        f"{resume_summary[:6000]}\n\n"
        "JOB DESCRIPTION (title deliberately withheld)\n"
        f"{redacted[:9000]}\n\n"
        f"[{redactions} title mention(s) were redacted from this description]"
    )

    key = _cache_key(resume_summary[:6000], redacted[:9000])
    cached = _read_cache(key)
    if cached:
        return TeacherLabel(**cached["label"], cached=True)
    if not allow_network:
        return None

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 600,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "job_fit", "strict": True, "schema": SCHEMA},
        },
    }

    started = time.perf_counter()
    parsed = _call_with_retry(payload, timeout)
    if parsed is None:
        return None

    elapsed = (time.perf_counter() - started) * 1000
    label = TeacherLabel(
        decision=str(parsed["decision"]).upper(),
        primary_role_family=str(parsed.get("primary_role_family") or "other"),
        secondary_role_family=str(parsed.get("secondary_role_family") or ""),
        seniority_match=bool(parsed.get("seniority_match")),
        critical_mismatch=bool(parsed.get("critical_mismatch")),
        confidence=float(parsed.get("confidence") or 0.0),
        reason=str(parsed.get("reason") or "")[:400],
        latency_ms=round(elapsed, 1),
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
