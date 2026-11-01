"""Sorts review-blocking browser-automation errors into a fixed set of
categories, with plain deterministic rules and no model call.

Each blocking issue already carries its field metadata (label, type, options,
issue type), extracted deterministically by browser_verifier.py. The rules
below read that metadata and decide whether the issue is something the
candidate can answer and, if so, which question to ask: the field's own label,
so the saved answer keys straight back to what fill-time matching compares.

Owner's rule (2026-11-01): Autopilot fills, checks and stages applications with
deterministic code only. Nothing on this path calls an LLM.
"""

from __future__ import annotations

import logging
import re
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


_JOB_EXPIRED_HINTS = (
    "no longer accepting", "no longer available", "posting has closed", "posting is closed",
    "job has expired", "job is closed", "position has been filled", "job not found",
)
_MISMATCH_HINTS = ("doesn't match", "does not match", "conflicts with", "mismatch")
_DEMOGRAPHIC_WORDS = (
    "gender", "race", "ethnicity", "hispanic", "latino", "veteran", "disability",
    "sexual orientation", "pronoun", "transgender",
)
_AUTH_WORDS = (
    "sponsor", "visa", "work authori", "authorized to work", "legally authorized",
    "citizen", "export control", "u.s. person", "right to work", "work permit",
)
_COMP_WORDS = ("salary", "compensation", "pay expectation", "desired pay", "hourly rate", "expected pay")
_ACK_WORDS = (
    "acknowledge", "i agree", "consent", "certify", "attest", "hybrid", "on-site", "onsite",
    "in office", "in-office", "relocat", "commute",
)


#: "Required field 'Start date' was rejected as empty", "Field \"Pronouns\" is required".
_QUOTED_FIELD_RE = re.compile(r"""field\s+['"‘“]([^'"’”]{2,200})['"’”]""", re.IGNORECASE)


def _label_from_reason(raw_reason: str) -> str:
    """The field label quoted in a raw reason, for issues stored without one
    (jobs staged before field metadata was captured)."""
    m = _QUOTED_FIELD_RE.search(raw_reason or "")
    return " ".join(m.group(1).split()) if m else ""


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def classify_review_issue(
    raw_reason: str,
    *,
    label: str = "",
    field_type: str = "",
    options: list[str] | None = None,
    issue_type: str = "",
) -> dict[str, Any]:
    """Classify one raw review-blocking reason into a stable category and, if the
    candidate can answer it, the question to ask.

    Returns {"category": <ReviewErrorCategory value>, "question": str | None}.
    Pure function of its inputs: the same issue always gets the same answer.
    """
    reason = " ".join((raw_reason or "").lower().split())
    clean_label = " ".join((label or "").split()) or _label_from_reason(raw_reason)
    lab = clean_label.lower()

    if _has_any(reason, _JOB_EXPIRED_HINTS):
        return {"category": ReviewErrorCategory.JOB_EXPIRED.value, "question": None}
    # The system wrote a wrong value: retyping an answer does not fix that,
    # a re-fill does, so it is not a question for the candidate.
    if (issue_type or "").upper() == "MISMATCH" or _has_any(reason, _MISMATCH_HINTS):
        return {"category": ReviewErrorCategory.AUTOFILL_MISMATCH.value, "question": None}
    if not clean_label or clean_label == "?":
        return {"category": ReviewErrorCategory.UNKNOWN.value, "question": None}

    if _has_any(lab, _DEMOGRAPHIC_WORDS):
        category = ReviewErrorCategory.DEMOGRAPHIC
    elif _has_any(lab, _AUTH_WORDS):
        category = ReviewErrorCategory.WORK_AUTHORIZATION
    elif _has_any(lab, _COMP_WORDS) or re.search(r"\bpay\b", lab):
        category = ReviewErrorCategory.COMPENSATION
    elif _has_any(lab, _ACK_WORDS):
        category = ReviewErrorCategory.ACKNOWLEDGMENT
    elif (issue_type or "").upper() == "MISSING_REQUIRED" or "required" in reason:
        category = ReviewErrorCategory.MISSING_FIELD
    else:
        return {"category": ReviewErrorCategory.UNKNOWN.value, "question": None}
    return {"category": category.value, "question": clean_label}


def issues_from_error_fields(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Blocking issues for the fields an ATS flagged after the submit click.

    A rejected submission ("This field is required.") produces no policy issues,
    so without this the job reaches review with nothing to answer.
    """
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field in evidence.get("errorFields") or []:
        label = " ".join(str(field.get("label") or "").split())
        if not label or label == "?" or label.lower() in seen:
            continue
        seen.add(label.lower())
        issues.append({
            "gate": "SUBMIT_VALIDATION",
            "label": label,
            "reason": f"Required field '{label}' was rejected as empty on submit.",
            "issueType": "MISSING_REQUIRED",
            "fieldType": field.get("fieldType") or "",
            "options": field.get("options") or [],
        })
    return issues


async def build_pending_questions(blocking_issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn a job's policy blocking-issues into the structured, answerable
    questions the Apply-board popup renders (dropdown when `options` is
    non-empty, text input otherwise).

    Shared by the live submission path (autopilot_runner) and the on-demand
    re-classification endpoint (for jobs staged before this existed) so the two
    never drift into two different notions of "what counts as a question."

    The aggregate "N fields unfilled" summary (`REQUIRED_FIELDS_CHECK`) is always
    dropped: it only restates the individual issues already in the same list.
    Kept async so both callers stay unchanged.
    """
    pending_questions = []
    seen: set[str] = set()
    for bi in blocking_issues:
        if bi.get("gate") == "REQUIRED_FIELDS_CHECK":
            continue
        cls = classify_review_issue(
            bi.get("reason", ""),
            label=bi.get("label", ""),
            field_type=bi.get("fieldType", ""),
            options=bi.get("options", []),
            issue_type=bi.get("issueType", ""),
        )
        if cls["category"] not in ANSWERABLE_CATEGORIES or not cls["question"]:
            continue
        raw_label = bi.get("label") or cls["question"]
        if raw_label.lower() in seen:
            continue
        seen.add(raw_label.lower())
        pending_questions.append({
            "question": cls["question"],
            # The raw DOM label: the key the saved answer is stored under,
            # since it is what fill-time matching (resolve_answer) compares.
            "rawLabel": raw_label,
            "category": cls["category"],
            "fieldType": bi.get("fieldType", ""),
            "options": bi.get("options", []),
        })
    return pending_questions
