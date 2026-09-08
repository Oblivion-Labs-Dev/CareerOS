"""Classify autopilot jobs the candidate can never apply to.

A posting is *ineligible* when the blocker is the posting itself, not the
automation and not a missing answer: it requires citizenship the candidate does
not hold, refuses visa sponsorship the candidate needs, sits outside the United
States, or is simply gone. None of those become applyable by retrying or by the
user answering a question, so they must not sit in the review or retry queues —
that is exactly what makes a review queue useless to work through.

This is deliberately conservative. Anything that *might* be a transient
automation failure (a timeout, a detached frame, a selector miss) stays FAILED so
it still gets retried, and anything blocked only on a missing answer stays in
review so the user can supply it.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.application_assistant.domain import IneligibilityReason

# Ordered: the first match wins, so the most specific/explanatory reason is
# checked before broader ones.
_ERROR_TEXT_RULES: tuple[tuple[IneligibilityReason, tuple[str, ...]], ...] = (
    (
        IneligibilityReason.REQUIRES_US_CITIZENSHIP,
        (
            r"requires? u\.?s\.? citizenship",
            r"u\.?s\.? citizenship\s*/?\s*itar",
            r"\bitar\b",
            r"citizenship\s*/\s*clearance",
            r"u\.?s\.? citizens? only",
            r"security clearance",
        ),
    ),
    (
        IneligibilityReason.NO_VISA_SPONSORSHIP,
        (
            r"does not sponsor",
            r"no (?:visa )?sponsorship",
            r"not (?:able to )?sponsor",
            r"unable to sponsor",
            r"without (?:visa )?sponsorship",
        ),
    ),
    (
        IneligibilityReason.OUTSIDE_UNITED_STATES,
        (
            r"outside the united states",
            r"does not match united states criteria",
            r"not.*(?:united states|u\.?s\.?)\s*(?:based|location)",
        ),
    ),
    (
        IneligibilityReason.POSTING_EXPIRED,
        (
            r"posting has expired",
            r"expired or was removed",
            r"unlisted / expired",
            r"no longer (?:open|active|accepting)",
            r"no application form on the page",
            r"appears to be closed or redirected",
            r"job(?:ing)? posting (?:is )?closed",
        ),
    ),
)

# Boards that exist only for testing/demo purposes — applying to them is
# meaningless, and they otherwise pollute the review queue with fake questions.
_SANDBOX_COMPANY_PATTERNS = (
    r"examplecorp",
    r"\bsandbox\b",
    r"\bdemo\b(?!crat)",
    r"\btest company\b",
)


def _first_text_match(text: str) -> IneligibilityReason | None:
    for reason, patterns in _ERROR_TEXT_RULES:
        for pattern in patterns:
            if re.search(pattern, text, re.I):
                return reason
    return None


def classify_ineligibility(job: dict[str, Any]) -> tuple[IneligibilityReason, str] | None:
    """Return (reason, human-readable detail) if `job` can never be applied to.

    Returns None when the job is still actionable — either genuinely retryable or
    waiting on an answer from the user.
    """
    company = str(job.get("company") or "")
    for pattern in _SANDBOX_COMPANY_PATTERNS:
        if re.search(pattern, company, re.I):
            return (
                IneligibilityReason.NOT_A_REAL_POSTING,
                f"'{company}' is a sandbox/demo job board, not a real employer posting.",
            )

    # The runner records why it gave up in one of these, depending on the path
    # taken (hard filter vs. executor result vs. exception handler).
    haystack = " ".join(
        str(job.get(key) or "")
        for key in ("skipReason", "lastError", "aiExplanation", "lastErrorType")
    )
    reason = _first_text_match(haystack)
    if reason is not None:
        detail = (
            str(job.get("skipReason") or "").strip()
            or str(job.get("lastError") or "").strip()
            or str(job.get("aiExplanation") or "").strip()
        )
        return reason, detail

    return None


def apply_ineligibility(job: dict[str, Any], reason: IneligibilityReason, detail: str) -> dict[str, Any]:
    """Mark `job` INELIGIBLE in place, recording the exact reason."""
    from app.services.application_assistant.domain import AutopilotJobStatus

    job["status"] = AutopilotJobStatus.INELIGIBLE.value
    job["ineligibilityReason"] = reason.value
    job["ineligibilityDetail"] = detail
    # Keep it out of every retry path: reprocess-failed/-skipped and the
    # self-healer all key off status, and a permanently ineligible job must not
    # be resurrected by them.
    job["hasPersistentBlock"] = True
    return job
