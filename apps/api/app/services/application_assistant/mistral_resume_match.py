"""Mistral-via-Ollama semantic match between a job description and the real resume.

The Autopilot queue used to rank postings with a keyword-overlap heuristic
(``qwen_job_match.evaluate_job_match`` -> ``job_matching.match_job``), which is
why queued rows carried ``matchReasons`` like ``["engineering", "senior",
"never"]``. This module replaces that for queue ranking with an actual
resume/JD comparison performed by Mistral running locally under Ollama, and
persists the four fields the queue is sorted and explained by:

    matchScore | matchReason | keyMatchingSkills | missingSkills

Anti-fabrication is enforced in code, not just in the prompt: every skill the
model claims as a *match* must be evidenced somewhere in the candidate's real
resume / profile / accomplishments text. Anything it invented is dropped from
``keyMatchingSkills`` (and folded into ``missingSkills`` when the posting asked
for it), and the score is re-derived from what survived so a hallucinated skill
can never inflate a job's queue position.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Callable
from typing import Any

from app.services.application_assistant.candidate_match_context import (
    build_candidate_skill_terms,
    build_candidate_summary_for_llm,
)
from app.services.application_assistant.llm_client import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_LOCAL_MODEL,
    LLMClient,
)

logger = logging.getLogger(__name__)

# Deliberately an explicit Ollama client rather than ``create_llm_client``:
# queue match scoring must be Mistral-on-Ollama, not whichever provider the
# stored settings happen to point at (Gemini / OpenAI / OpenRouter).
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
# Follows the app-wide local default (Qwen3) unless explicitly overridden, so
# queue scoring and the rest of CareerOS never silently run different models.
MATCH_MODEL = os.environ.get("CAREEROS_MATCH_MODEL", DEFAULT_LOCAL_MODEL)
# A warm 7B scoring pass measures ~10-20s on this box; the first call after an
# idle period also pays the model load, so this covers a cold start.
MATCH_TIMEOUT = int(os.environ.get("CAREEROS_MATCH_TIMEOUT", "180"))

MATCH_METHOD = "ollama-local"

MATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "matchScore": {"type": "number"},
        "matchReason": {"type": "string"},
        "keyMatchingSkills": {"type": "array", "items": {"type": "string"}},
        "missingSkills": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["matchScore", "matchReason", "keyMatchingSkills", "missingSkills"],
}

MATCH_SYSTEM = """You compare ONE job description against ONE candidate resume and score the fit.

Rules you must follow:
- Only list a skill under "keyMatchingSkills" if it appears in the candidate's
  resume/profile text that you were given. Never infer, upgrade, or invent a
  skill the candidate did not write down.
- Put requirements the posting asks for that the resume does NOT evidence under
  "missingSkills".
- Every entry in both skill lists is a SHORT skill name of 1-4 words, copied in
  the candidate's or the posting's own wording ("Kubernetes", "distributed
  systems", "C#", "Go"). Never write a sentence or a phrase starting with
  "Experience with" / "Proficiency in" / "Ability to".
- "matchReason" is 1-2 factual sentences explaining the score. No advice, no
  encouragement, no recommendation to apply.

Return JSON only:
{
  "matchScore": 0-100,
  "matchReason": "1-2 factual sentences",
  "keyMatchingSkills": ["skill from the resume that the job requires"],
  "missingSkills": ["requirement the resume does not evidence"]
}

Score calibration:
- 90-100: meets essentially every requirement with direct resume evidence
- 75-89:  strong fit, most requirements evidenced
- 55-74:  partial fit, meaningful gaps
- 35-54:  weak fit, significant gaps
- 0-34:   poor fit"""

_FILLER_TOKENS = {
    "and", "the", "for", "with", "experience", "strong", "years", "year",
    "knowledge", "skills", "skill", "using", "including", "such", "etc",
    "ability", "proficiency", "proficient", "familiarity", "familiar",
    "understanding", "working", "hands", "solid", "deep", "plus", "level",
}


def build_mistral_match_client(*, timeout: int | None = None) -> LLMClient:
    """Local Mistral client used for queue match scoring.

    No fallback is configured on purpose: if Ollama is down we want the caller
    to fall back to the deterministic heuristic and say so in ``matchMethod``,
    rather than silently scoring the queue with a different vendor's model.
    """
    return LLMClient(
        base_url=OLLAMA_BASE_URL,
        model=MATCH_MODEL,
        api_key="",
        timeout=timeout or MATCH_TIMEOUT,
        max_retries=1,
        provider="ollama",
        context_window=DEFAULT_CONTEXT_WINDOW,
    )


def _truncate(text: str, limit: int) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


# The model is asked for bare skill names but still reaches for resume-speak.
# Stripping the carrier phrase turns "Experience with distributed systems" into
# the skill itself, so the evidence check compares real terms instead of
# failing on the words "experience" and "with".
_SKILL_PREFIX_RE = re.compile(
    r"^(?:strong\s+|solid\s+|deep\s+|hands[- ]on\s+|proven\s+|demonstrated\s+|extensive\s+)?"
    r"(?:experience|expertise|proficiency|proficient|familiarity|familiar|knowledge|background|skills?|ability|able)"
    r"\s+(?:in|with|of|using|building|working\s+with|to)\s+",
    re.I,
)


def _clean_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = re.sub(r"\s+", " ", str(item)).strip(" .;,-")
        text = _SKILL_PREFIX_RE.sub("", text).strip(" .;,-")
        if not text or len(text) > 80:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _is_evidenced(skill: str, evidence_text: str, evidence_terms: set[str]) -> bool:
    """True when the candidate's own documents actually mention this skill.

    A claimed skill counts as evidenced when its exact phrase appears in the
    candidate text, or when every meaningful token of it does (so "distributed
    systems" matches a resume saying "distributed system design", and "C#"
    matches "C#/.NET"). Filler tokens are stripped first so a two-word claim
    cannot pass on the strength of the word "experience" alone.
    """
    normalized = skill.lower().strip()
    if not normalized:
        return False
    if normalized in evidence_text:
        return True

    tokens = [t for t in re.findall(r"[a-z0-9+#\.]{2,}", normalized) if t not in _FILLER_TOKENS]
    if not tokens:
        return False
    return all(token in evidence_terms or token in evidence_text for token in tokens)


def _score_from_evidence(
    raw_score: float,
    matched: list[str],
    dropped: list[str],
) -> float:
    """Re-derive the score once unevidenced claims are removed.

    The model's own number is the ceiling; each fabricated "match" it leaned on
    costs the job real ground, so a posting can never out-rank an honestly
    scored one by inventing skills.
    """
    score = max(0.0, min(100.0, float(raw_score)))
    if not dropped:
        return round(score, 1)
    claimed = len(matched) + len(dropped)
    if claimed == 0:
        return round(score, 1)
    kept_ratio = len(matched) / claimed
    # Blend toward the honest ratio rather than zeroing out: a job with four
    # real matches and one invented one should lose a little, not collapse.
    adjusted = score * (0.55 + 0.45 * kept_ratio)
    return round(max(0.0, min(100.0, adjusted)), 1)


def is_empty_payload(parsed: dict[str, Any]) -> bool:
    """True when the model answered with nothing usable.

    Mistral occasionally returns a schema-shaped but entirely blank object. That
    is a failed score, not a genuine zero — persisting it as ``matchScore: 0``
    would bury a real posting at the bottom of the queue for a model hiccup, so
    callers treat this as "unscored" and try again later.
    """
    return (
        not str(parsed.get("matchReason") or "").strip()
        and not _clean_list(parsed.get("keyMatchingSkills"), 1)
        and not _clean_list(parsed.get("missingSkills"), 1)
        and float(parsed.get("matchScore") or 0.0) <= 0.0
    )


def sanitize_match_payload(
    parsed: dict[str, Any],
    *,
    evidence_text: str,
    evidence_terms: set[str],
) -> dict[str, Any]:
    """Strip fabricated skills out of a raw model payload and re-derive the score."""
    claimed_matches = _clean_list(parsed.get("keyMatchingSkills"), 20)
    missing = _clean_list(parsed.get("missingSkills"), 20)

    matched: list[str] = []
    fabricated: list[str] = []
    for skill in claimed_matches:
        if _is_evidenced(skill, evidence_text, evidence_terms):
            matched.append(skill)
        else:
            fabricated.append(skill)

    # A "match" the resume does not evidence is, by definition, a gap.
    missing_keys = {m.lower() for m in missing}
    for skill in fabricated:
        if skill.lower() not in missing_keys:
            missing.append(skill)
            missing_keys.add(skill.lower())

    reason = re.sub(r"\s+", " ", str(parsed.get("matchReason") or "")).strip()
    if not reason:
        reason = "Mistral compared this posting against the resume."
    if fabricated:
        reason = (
            f"{reason} ({len(fabricated)} claimed skill(s) had no resume evidence "
            f"and were removed: {', '.join(fabricated[:4])})"
        ).strip()

    score = _score_from_evidence(float(parsed.get("matchScore") or 0.0), matched, fabricated)

    return {
        "matchScore": score,
        "matchReason": _truncate(reason, 600),
        "keyMatchingSkills": matched[:12],
        "missingSkills": missing[:12],
        "matchMethod": MATCH_METHOD,
        "matchModel": MATCH_MODEL,
        "unevidencedClaimsDropped": fabricated[:12],
    }


def build_candidate_evidence(
    profile: dict[str, Any],
    *,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
) -> tuple[str, str, set[str]]:
    """Return ``(llm_summary, lowercased_evidence_text, evidence_token_set)``."""
    summary = build_candidate_summary_for_llm(
        profile, documents=documents, accomplishments=accomplishments
    )
    terms = build_candidate_skill_terms(
        profile, documents=documents, accomplishments=accomplishments
    )
    return summary, summary.lower(), terms


async def score_job_against_resume(
    client: LLMClient,
    job: dict[str, Any],
    *,
    candidate_summary: str,
    evidence_text: str,
    evidence_terms: set[str],
) -> dict[str, Any] | None:
    """Score one posting with Mistral. Returns None when the model is unusable."""
    if not client.enabled or not candidate_summary.strip():
        return None

    description = _truncate(str(job.get("description") or ""), 4500)
    prompt = (
        f"Job title: {job.get('title') or 'Unknown role'}\n"
        f"Company: {job.get('company') or ''}\n"
        f"Location: {job.get('location') or ''}\n\n"
        f"Job description:\n{description or '(no description provided)'}\n\n"
        f"Candidate resume and profile:\n{_truncate(candidate_summary, 7000)}"
    )

    try:
        result = await client.complete(
            prompt, system=MATCH_SYSTEM, response_schema=MATCH_SCHEMA, task="jd_resume_match"
        )
    except Exception as exc:  # network/runtime issues must not kill the queue
        logger.warning("Mistral match scoring raised for %s: %s", job.get("id"), exc)
        return None

    if not result.get("success") or not isinstance(result.get("data"), dict):
        logger.info(
            "Mistral match scoring unavailable for %s: %s",
            job.get("id"),
            str(result.get("error"))[:200],
        )
        return None

    if is_empty_payload(result["data"]):
        logger.info("Mistral returned an empty match payload for %s — leaving unscored", job.get("id"))
        return None

    return sanitize_match_payload(
        result["data"], evidence_text=evidence_text, evidence_terms=evidence_terms
    )


async def score_jobs_against_resume(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
    concurrency: int = 2,
    client: LLMClient | None = None,
    should_continue: "Callable[[], bool] | None" = None,
) -> dict[str, dict[str, Any]]:
    """Score many postings. Returns ``{job id: match payload}`` for those that scored.

    Concurrency stays low by default — this shares one local GPU with the
    resume tailoring of the application that is actively running, and starving
    that of the model is worse than scoring the backlog a little slower.
    """
    if not jobs:
        return {}

    summary, evidence_text, evidence_terms = build_candidate_evidence(
        profile, documents=documents, accomplishments=accomplishments
    )
    if not summary.strip():
        return {}

    llm = client or build_mistral_match_client()
    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: dict[str, dict[str, Any]] = {}

    async def one(job: dict[str, Any]) -> None:
        async with semaphore:
            # Re-checked per job, not once per batch: a batch takes minutes and
            # an application can start at any point inside it. Whatever has been
            # scored so far is kept and the rest is picked up next cycle.
            if should_continue is not None and not should_continue():
                return
            payload = await score_job_against_resume(
                llm,
                job,
                candidate_summary=summary,
                evidence_text=evidence_text,
                evidence_terms=evidence_terms,
            )
            if payload is not None:
                results[str(job.get("id") or "")] = payload

    await asyncio.gather(*(one(job) for job in jobs))
    return results
