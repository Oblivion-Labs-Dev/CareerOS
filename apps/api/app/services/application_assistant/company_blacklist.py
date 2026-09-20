"""The candidate's own do-not-apply list.

Adapted from career-ops's `data/blacklist.md` check in its `apply` mode: a
company the candidate has personally decided never to apply to again (a past
rejection that soured, a culture red flag surfaced in research, a recruiter who
was hostile). That decision belongs to the candidate, not to anything the
automation infers about a posting — which is why this is a plain list kept in
Settings, checked before a queued job is ever claimed, rather than a signal
computed from job data the way `company_cap.py`'s pacing or
`posting_legitimacy.py`'s scam signals are.

This is deliberately unlike `company_cap`'s hold: a cap is temporary and lifts
when its window rolls, so a held job stays QUEUED. A blacklist entry is a
standing decision with no expiry, so a blacklisted job is filed INELIGIBLE —
a genuine dead end for this candidate, exactly like a citizenship bar or an
expired posting (see the project's own bucket semantics), not something to
hold and retry.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.application_assistant.company_cap import normalise_company
from app.services.application_assistant.domain import AutopilotJobStatus, IneligibilityReason


def blacklist_reasons(blacklist: list[Mapping[str, Any]] | None) -> dict[str, str]:
    """Map normalised company name -> the candidate's own recorded reason."""
    out: dict[str, str] = {}
    for entry in blacklist or []:
        company = normalise_company(entry.get("company"))
        if company:
            out[company] = str(entry.get("reason") or "").strip()
    return out


def is_blacklisted(company: Any, blacklist: list[Mapping[str, Any]] | None) -> str | None:
    """The candidate's reason if `company` is on the list, else None."""
    return blacklist_reasons(blacklist).get(normalise_company(company))


def partition_by_blacklist(
    queued: list[dict[str, Any]],
    blacklist: list[Mapping[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split `queued` into (allowed, blocked), mutating blocked jobs in place
    to record why — mirrors `company_cap.partition_by_cap`'s shape so callers
    that already know that function know this one.
    """
    reasons = blacklist_reasons(blacklist)
    if not reasons:
        return list(queued), []

    allowed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for job in queued:
        reason = reasons.get(normalise_company(job.get("company")))
        if reason is None:
            allowed.append(job)
            continue
        job["status"] = AutopilotJobStatus.INELIGIBLE.value
        job["ineligibilityReason"] = IneligibilityReason.COMPANY_BLACKLISTED.value
        job["ineligibilityDetail"] = (
            f"{job.get('company') or 'This company'} is on your do-not-apply list: {reason}"
            if reason
            else f"{job.get('company') or 'This company'} is on your do-not-apply list."
        )
        blocked.append(job)
    return allowed, blocked
