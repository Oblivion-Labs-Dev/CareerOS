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

from collections.abc import Iterable

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
            r"international location",
            r"non-?us location",
            r"outside target geography",
        ),
    ),
    (
        # The automation reached a live posting but there is no form it can
        # drive from that URL: the employer's apply flow starts somewhere else
        # (Workday's account-gated flow, a custom careers app, or a listing on
        # a site that is not a job board at all). None of that is breakage and
        # none of it is expiry - the posting is open and the candidate can
        # submit it by hand - so it belongs in manual review, not in FAILED
        # where it would be retried forever, and not in a terminal bucket where
        # a real opportunity would be buried.
        #
        # Observed in one batch of ten: a CrowdStrike Workday posting, a
        # ByteDance careers-app posting, and a Hacker News "who is hiring"
        # thread, all three recorded as technical failures.
        IneligibilityReason.MANUAL_APPLICATION_REQUIRED,
        (
            r"no application form on the posting page",
            r"apply flow starts elsewhere",
            r"cannot be driven from this url",
            # Workday keeps its eight-step wizard behind a per-employer
            # candidate account. The posting is live and the candidate can
            # apply by hand; the automation will not create accounts or type
            # passwords, so this is manual by policy, not by breakage.
            r"workday requires a candidate account",
            r"requires a candidate account",
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
            r"is a careers index, not a specific posting",
            r"posting has no application url",
        ),
    ),
    (
        IneligibilityReason.BOT_PROTECTED_BOARD,
        (
            r"cloudflare turnstile",
            r"\brecaptcha\b",
            r"\bcaptcha\b",
            r"bot[- ]protected",
            r"bot challenge",
            r"bot protection",
            # "Persistent block or expired link" is written by the runner when a
            # retry fails, and it names two different things. A *block* means the
            # automation could not drive the page — the posting is live and the
            # user can submit it by hand. Treating that phrase as evidence of
            # expiry sent working postings to a terminal bucket: reported live
            # for a Databricks listing whose link opens fine.
            #
            # Where the wording cannot distinguish a dead posting from a blocked
            # one, the safe reading is blocked. A live job wrongly marked expired
            # disappears from the list the user works through; a dead job in
            # manual review costs one click to dismiss.
            r"persistent block or expired link",
            # A redirect to a careers index is not proof the posting is gone.
            # Boards bounce automated requests to their index, and the original
            # link often still works in a browser — observed on a Robinhood
            # Greenhouse posting that opens normally.
            r"redirected to careers site",
            # SmartRecruiters fronts its apply flow with DataDome, which serves a
            # challenge and an otherwise empty page — the word "captcha" never
            # appears in the failure text.
            r"\bdatadome\b",
            r"\bhcaptcha\b",
            r"excluded contractor or bot",
            # Ashby refuses automated posts server-side instead of showing a
            # challenge: the form stays put and this sentence is the only
            # signal. No iframe and no "captcha" wording, so the DOM sweep in
            # the executor never sees it.
            r"flagged as (?:possible|potential) spam",
            # job_filter_ranker's Roblox hard-filter reason, reworded to describe
            # the symptom rather than claim a Turnstile wall. Without a match
            # here the claim-time check falls through and every queued Roblox
            # job burns a ~9-minute browser attempt ending in "no application form".
            r"reliably times out in careeros's automation",
        ),
    ),
    (
        IneligibilityReason.REQUIRES_UNAVAILABLE_INFORMATION,
        (
            r"requires? (?:an? )?undergraduate gpa",
            r"gpa as a mandatory",
            r"profile has no gpa",
            r"unverifiable technical experience",
            r"requires affirming",
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


# The review list is for applications a human can still finish: the posting is
# live, but deterministic filling could not complete it. Everything below is a
# dead end instead — either the posting no longer exists, or the candidate is
# barred from it outright — so it goes to a terminal bucket rather than
# cluttering the list the user works through by hand.
# INELIGIBLE means one thing only: the candidate is barred from the role
# (repo owner, 2026-09-23 - "ineligible is like no visa sponsorship or US
# citizen"). Their own standing exclusions (a blacklisted company, an excluded
# kind of role) are the same kind of "not for me".
TERMINAL_REASONS = frozenset({
    IneligibilityReason.REQUIRES_US_CITIZENSHIP,
    IneligibilityReason.NO_VISA_SPONSORSHIP,
    IneligibilityReason.OUTSIDE_UNITED_STATES,
    IneligibilityReason.COMPANY_BLACKLISTED,
    IneligibilityReason.ROLE_EXCLUDED,
})

# Dead ends that can never be retried: there is no posting left to apply to, or
# the candidate already applied. These are FAILED - "failed, cannot retry".
FAILED_REASONS = frozenset({
    IneligibilityReason.POSTING_EXPIRED,
    IneligibilityReason.NOT_A_REAL_POSTING,
    IneligibilityReason.DUPLICATE_APPLICATION,
})

# Not dead ends, but not automatable either: the posting is live and the
# candidate can submit it by hand, the automation simply cannot. These go to
# MANUAL_REVIEW so they stay visible as real opportunities instead of being
# buried in the terminal bucket or cluttering the answer-a-question review list.
MANUAL_REASONS = frozenset({
    IneligibilityReason.BOT_PROTECTED_BOARD,
    IneligibilityReason.MANUAL_APPLICATION_REQUIRED,
})


def apply_ineligibility(job: dict[str, Any], reason: IneligibilityReason, detail: str) -> dict[str, Any]:
    """Record why an attempt could not be completed.

    Review is specifically for postings that are still open but that deterministic
    filling could not complete — a board the automation cannot drive, or a form
    demanding a fact the profile does not hold. Those stay visible so the user can
    open the posting and finish it by hand. A posting that is closed, expired or
    fake (or a duplicate of one already applied to) is FAILED - a dead end that is
    never retried. Only a role the candidate is barred from outright is INELIGIBLE.
    """
    from app.services.application_assistant.domain import AutopilotJobStatus

    job["ineligibilityReason"] = reason.value
    job["ineligibilityDetail"] = detail
    if reason in MANUAL_REASONS:
        job["status"] = AutopilotJobStatus.MANUAL_REVIEW.value
        # Still a persistent block for the automation: no retry will get past a
        # CAPTCHA, so the runner must not keep picking it up.
        job["hasPersistentBlock"] = True
        return job
    if reason in FAILED_REASONS:
        job["status"] = AutopilotJobStatus.FAILED.value
        # Never retried: every retry path skips FAILED and persistent blocks.
        job["hasPersistentBlock"] = True
        job.pop("technicalFailure", None)
        return job
    if reason in TERMINAL_REASONS:
        job["status"] = AutopilotJobStatus.INELIGIBLE.value
        # Keep it out of every retry path: reprocess-failed/-skipped and the
        # self-healer all key off status, and a permanently ineligible job must
        # not be resurrected by them.
        job["hasPersistentBlock"] = True
        return job

    job["status"] = AutopilotJobStatus.NEEDS_REVIEW.value
    job["lastError"] = detail or reason.value
    job["aiExplanation"] = detail or reason.value
    # Not a persistent block: the user may fix the underlying problem (answer the
    # question, apply by hand) and requeue it themselves.
    job["hasPersistentBlock"] = False
    return job


def duplicate_url_key(url: Any) -> str:
    """The form of an application URL that `find_duplicate_submission` compares."""
    return str(url or "").strip().rstrip("/").casefold()


def duplicate_field_key(value: Any) -> str:
    """The form of a company or title that `find_duplicate_submission` compares."""
    return str(value or "").strip().casefold()


def _identity(job: dict[str, Any]) -> tuple[str, str]:
    """The (company, title) pair that identifies one posting to a human."""
    return duplicate_field_key(job.get("company")), duplicate_field_key(job.get("title"))


def find_duplicate_submission(
    job: dict[str, Any], submitted_jobs: Iterable[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return an already-submitted application for the same posting, if any.

    An ATS silently refuses a second application to the same posting: the form
    simply stays on screen, which the executor reports as "submit button is
    still active" — a technical-sounding failure that says nothing about the
    real cause and burns a full submission attempt to discover it.

    Matching is by application URL *and* by (company, title), because the two
    catch different cases. The URL misses a posting whose earlier row predates
    URL capture (observed: an Affirm application submitted with a null
    applicationUrl), and company+title misses a posting the employer re-listed
    under a new title. Either match is enough.
    """
    from app.services.application_assistant.persistence import ats_posting_identity

    url = duplicate_url_key(job.get("applicationUrl"))
    company, title = _identity(job)
    # The ATS posting id catches the same posting under another URL shape and
    # title wording, which neither of the above does (#37).
    posting = ats_posting_identity(job)
    for other in submitted_jobs:
        if other.get("id") == job.get("id"):
            continue
        other_url = duplicate_url_key(other.get("applicationUrl"))
        if url and other_url and url == other_url:
            return other
        if company and title and _identity(other) == (company, title):
            return other
        if posting and ats_posting_identity(other) == posting:
            return other
    return None
