"""Decide what an attempt that did not confirm actually proved.

There are two very different ways an application attempt can end without a
confirmation, and collapsing them into one bucket is what let CareerOS apply
twice to the same posting:

* **Proven not submitted.** The form never loaded, the submit button was never
  found, pre-submit validation refused the attempt. Nothing reached the
  employer, so retrying is free and correct. This is ``FAILED``.
* **Unproven.** The final submit was clicked and then the thread was lost — the
  confirmation never rendered, the page timed out, the browser died, the process
  was killed mid-verify. The employer may well have the application. This is
  ``SUBMISSION_UNKNOWN``, and automation must never retry it.

The deciding evidence is whether the submit click was actually issued, which the
executor records durably via its ``on_submit_attempt`` callback *before* it
clicks. Anything after that point is unproven unless a confirmation was read.

Before this existed, the unproven case was written as ``FAILED``. Both
``/autopilot/reprocess-failed`` and the in-run transient retry put a ``FAILED``
job straight back on the queue, and every duplicate guard excludes the job's own
record (``exclude_id=job["id"]``) — so nothing stopped a second application to a
posting that already had one. A late confirmation email was the only thing that
rescued it, which is precisely why a delayed or missing email produced a
duplicate.
"""

from __future__ import annotations

from typing import Any

from app.services.application_assistant.domain import (
    ApplicationErrorType,
    AutopilotJobStatus,
)

#: Executor evidence proving the attempt stopped before anything was sent.
#: Each of these is written by the executor on a path that returns *before* the
#: final submit click, so none of them can coexist with a real submission.
_PROOF_OF_NO_SUBMISSION = (
    "noApplicationForm",
    "preSubmitValidationErrors",
    "unresolvedRequiredFields",
)

#: Error wording that names a stage strictly earlier than the submit click.
_PRE_SUBMIT_ERRORS = (
    "submit button not found",
    "no application form",
    "posting appears to be closed",
)


def submit_was_attempted(job: dict[str, Any]) -> bool:
    """True once the final submit click has been issued for this attempt.

    Set durably by the executor immediately before clicking, so it survives a
    crash, a killed process and an expired lease.
    """
    return bool(job.get("submitAttemptedAt"))


def outcome_is_proven_unsubmitted(
    job: dict[str, Any], result: dict[str, Any] | None = None
) -> bool:
    """True only when the attempt demonstrably sent nothing to the employer.

    Deliberately conservative: this must return ``False`` whenever there is any
    doubt, because ``False`` routes to review and ``True`` authorises a retry
    that could apply a second time.
    """
    result = result or {}
    evidence = result.get("evidence") or {}

    # The click is the point of no return. Once it has been issued, no
    # after-the-fact signal can prove the employer did not receive the form.
    if submit_was_attempted(job):
        return False

    if any(evidence.get(key) or result.get(key) for key in _PROOF_OF_NO_SUBMISSION):
        return True

    message = str(result.get("error") or job.get("lastError") or "").lower()
    if any(phrase in message for phrase in _PRE_SUBMIT_ERRORS):
        return True

    # No submit attempt was ever recorded and nothing else is known. The click
    # never happened, so there is nothing at the employer to duplicate.
    return True


def classify_unproven_outcome(
    job: dict[str, Any], result: dict[str, Any] | None = None
) -> tuple[str, str | None]:
    """Status and error type for an attempt that ended without a confirmation.

    Returns ``(status, error_type)``. ``error_type`` is ``None`` when the caller
    should keep whatever it had already classified.

    A proven-unsent attempt is retryable, so it goes to NEEDS_REVIEW tagged
    ``technicalFailure``. FAILED is reserved for dead ends that can never be
    retried (repo owner, 2026-09-23), so nothing here produces it any more.
    """
    if outcome_is_proven_unsubmitted(job, result):
        job["technicalFailure"] = True
        return AutopilotJobStatus.NEEDS_REVIEW.value, None
    job.pop("technicalFailure", None)
    return (
        AutopilotJobStatus.SUBMISSION_UNKNOWN.value,
        ApplicationErrorType.SUBMISSION_UNCERTAIN.value,
    )


def is_retryable_technical_failure(job: dict[str, Any]) -> bool:
    """A job parked in review only because an attempt broke before submitting.

    These are what "retry failed" and the self-healer act on: the automation
    can simply try again, nothing is waiting on the user, and the submit click
    was never issued, so a retry cannot apply twice.
    """
    return (
        job.get("status") == AutopilotJobStatus.NEEDS_REVIEW.value
        and bool(job.get("technicalFailure"))
        and not submit_was_attempted(job)
        and not job.get("pendingQuestions")
        and not job.get("ineligibilityReason")
    )


def explain_unknown_submission(job: dict[str, Any]) -> str:
    """The sentence shown on a job parked as SUBMISSION_UNKNOWN."""
    when = str(job.get("submitAttemptedAt") or "")[:19].replace("T", " ")
    stamp = f" at {when} UTC" if when else ""
    return (
        f"The submit button was clicked{stamp} but no confirmation could be read, "
        "so this application may or may not have reached the employer. Autopilot "
        "will not retry it. Open the posting to check whether your application is "
        "there, then record the outcome — a confirmation email will resolve it "
        "automatically if one arrives."
    )
