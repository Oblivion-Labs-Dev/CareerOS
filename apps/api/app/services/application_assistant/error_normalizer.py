"""Normalizes non-deterministic browser-automation review errors into a fixed
set of deterministic categories, using an LLM classification step with a safe,
fully-deterministic fallback when the model call fails or returns junk.

Browser automation surfaces a wide, unpredictable variety of raw DOM-verification
error strings — radio groups, autocomplete mismatches, ATS-specific wording that
changes per employer. Rather than growing an ever-longer set of string-matching
heuristics for every phrasing we happen to have seen, each raw reason plus its
known field metadata (label/type/options, already extracted deterministically by
browser_verifier.py) is handed to a small local model that classifies it into one
of a stable enum and, when it represents something the candidate can answer,
produces one clean question.

Deterministic code still decides what to DO with each category (ask, retry, or
block) — the model only interprets text, it never makes the submit/block decision.
Same Mistral-primary / Gemini-fallback pair used for resume tailoring elsewhere in
this service, so classification degrades to the fallback model rather than failing
outright, and to the deterministic heuristic below rather than blocking on the LLM
entirely if both are unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum
from typing import Any

logger = logging.getLogger("career_os.error_normalizer")


class ReviewErrorCategory(str, Enum):
    ACKNOWLEDGMENT = "ACKNOWLEDGMENT"          # Yes/No consent (hybrid work, relocation, policy ack)
    DEMOGRAPHIC = "DEMOGRAPHIC"                # EEOC-style self-identification
    WORK_AUTHORIZATION = "WORK_AUTHORIZATION"  # visa / sponsorship / citizenship
    COMPENSATION = "COMPENSATION"              # salary or rate expectation
    MISSING_FIELD = "MISSING_FIELD"            # any other genuinely required text/select field
    AUTOFILL_MISMATCH = "AUTOFILL_MISMATCH"    # the system filled in a WRONG value — not user-answerable
    DATA_CONTRADICTION = "DATA_CONTRADICTION"  # candidate's own profile facts conflict
    JOB_EXPIRED = "JOB_EXPIRED"                # posting itself is closed or removed
    UNKNOWN = "UNKNOWN"                        # couldn't classify — treated conservatively as non-answerable


# Categories a candidate can resolve by typing/selecting a single answer.
ANSWERABLE_CATEGORIES = {
    ReviewErrorCategory.ACKNOWLEDGMENT.value,
    ReviewErrorCategory.DEMOGRAPHIC.value,
    ReviewErrorCategory.WORK_AUTHORIZATION.value,
    ReviewErrorCategory.COMPENSATION.value,
    ReviewErrorCategory.MISSING_FIELD.value,
}

_VALID_CATEGORIES = {c.value for c in ReviewErrorCategory}

_CATEGORY_GUIDE = """- ACKNOWLEDGMENT: a yes/no consent question (hybrid work, relocation, policy acknowledgment).
- DEMOGRAPHIC: EEOC-style self-identification (gender, race, veteran, disability).
- WORK_AUTHORIZATION: visa, sponsorship, or citizenship status.
- COMPENSATION: salary or rate expectation.
- MISSING_FIELD: any other genuinely required field a candidate could fill in directly.
- AUTOFILL_MISMATCH: the system filled in a WRONG value (e.g. wrong city/country) — retyping an answer doesn't fix this, it needs a re-fill.
- DATA_CONTRADICTION: the candidate's own profile facts conflict with each other.
- JOB_EXPIRED: the posting itself is closed, filled, or removed.
- UNKNOWN: none of the above fit."""


def _deterministic_fallback(label: str, issue_type: str) -> dict[str, Any]:
    """Used whenever the model is unavailable or returns something unusable —
    classification never blocks progress on an LLM call being up."""
    if issue_type == "MISSING_REQUIRED" and label.strip():
        return {"category": ReviewErrorCategory.MISSING_FIELD.value, "question": label.strip()}
    return {"category": ReviewErrorCategory.UNKNOWN.value, "question": None}


async def classify_review_issue(
    raw_reason: str,
    *,
    label: str = "",
    field_type: str = "",
    options: list[str] | None = None,
    issue_type: str = "",
) -> dict[str, Any]:
    """Classify one raw review-blocking reason into a stable category and, if the
    candidate can answer it, a single clean question.

    Returns {"category": <ReviewErrorCategory value>, "question": str | None}.
    Never raises — falls back to a deterministic heuristic on any model failure.
    """
    fallback = _deterministic_fallback(label, issue_type)
    try:
        from app.services.application_assistant.llm_client import create_llm_client

        client = create_llm_client()

        prompt = (
            "A browser-automation job-application filler hit this raw error while filling a form:\n"
            f"Raw error: {raw_reason}\n"
            f"Field label (if known): {label or 'unknown'}\n"
            f"Field type: {field_type or 'unknown'}\n"
            f"Available options (if a dropdown): {options or 'none'}\n\n"
            "Classify this into exactly one category from this fixed list:\n"
            f"{_CATEGORY_GUIDE}\n\n"
            "If the category is one a candidate can answer (ACKNOWLEDGMENT, DEMOGRAPHIC, WORK_AUTHORIZATION, "
            "COMPENSATION, MISSING_FIELD), rephrase the field label as ONE short, plain-language question a "
            "non-technical person could answer directly. Otherwise \"question\" must be null.\n\n"
            'Respond ONLY with JSON: {"category": "ONE_OF_THE_ENUM_VALUES", "question": "..." or null}'
        )

        res = await client.complete(
            prompt,
            system="You classify job-application form-filling errors into a fixed enum. Respond only with the requested JSON.",
        )
        if not res.get("success") or not res.get("data"):
            return fallback

        raw = res["data"].strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())

        category = parsed.get("category")
        if category not in _VALID_CATEGORIES:
            return fallback

        question = parsed.get("question")
        if category not in ANSWERABLE_CATEGORIES:
            question = None
        elif not question:
            question = label.strip() or fallback.get("question")

        return {"category": category, "question": question}
    except Exception as e:
        logger.warning("Review-issue classification failed, using deterministic fallback: %s", e)
        return fallback


async def build_pending_questions(blocking_issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify a job's full list of policy blocking-issues into the structured,
    answerable questions the Apply-board popup renders (dropdown when `options`
    is non-empty, text input otherwise).

    Shared by the live submission path (autopilot_runner) and the on-demand
    re-classification endpoint (for jobs staged before this existed) so the two
    never drift into two different notions of "what counts as a question."

    The aggregate "N fields unfilled" summary (`REQUIRED_FIELDS_CHECK`) is always
    dropped: it only restates the individual issues already in the same list, so
    classifying it too would just produce a duplicate question.
    """
    issues = [bi for bi in blocking_issues if bi.get("gate") != "REQUIRED_FIELDS_CHECK"]
    if not issues:
        return []

    # Throttle concurrency so local Ollama does not queue multiple heavy completions simultaneously
    sem = asyncio.Semaphore(1)

    async def _throttled_classify(bi: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            return await classify_review_issue(
                bi.get("reason", ""),
                label=bi.get("label", ""),
                field_type=bi.get("fieldType", ""),
                options=bi.get("options", []),
                issue_type=bi.get("issueType", ""),
            )

    classifications = await asyncio.gather(
        *[_throttled_classify(bi) for bi in issues],
        return_exceptions=True,
    )

    pending_questions = []
    for bi, cls in zip(issues, classifications):
        if isinstance(cls, BaseException) or not isinstance(cls, dict):
            continue
        if cls.get("category") in ANSWERABLE_CATEGORIES and cls.get("question"):
            pending_questions.append({
                "question": cls["question"],
                # The raw DOM label, not the model's rephrasing — used as the key
                # when saving the answer, since it's what fill-time matching
                # (resolve_answer) actually compares against and, unlike the
                # model's output, is deterministic across repeated attempts.
                "rawLabel": bi.get("label") or cls["question"],
                "category": cls["category"],
                "fieldType": bi.get("fieldType", ""),
                "options": bi.get("options", []),
            })
    return pending_questions
