"""Group stuck applications by shared root cause, count the eligible ones, rank.

Deterministic and model-free. It reuses the reason buckets the Applications view
and `/diagnostic/outcomes` already use (`diagnostic_outcomes`), and the same
requeue guard every retry path uses (`submission_outcome.requeue_refusal_reason`),
so a group here means the same thing as a reason filter in the UI.

A *signature* is the root cause, not the status: the reason bucket, the ATS the
posting lives on, and for blank-field failures the normalised field label. Two
jobs share a signature when one code fix would plausibly unblock both.

Only *eligible* applications count toward a group's size. Excluded are anything
the employer may already have (submitted, rejected, unknown outcome, a submit
click without proof of rejection), duplicates of such a posting, expired or
fake postings, jobs the queue classified ineligible, and jobs waiting on the
user's answers (those are counted in their own "needs your answers" group,
which no code change can resolve).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable
from urllib.parse import urlsplit

from app.services.application_assistant.persistence import canonical_application_url
from app.services.application_assistant.submission_outcome import requeue_refusal_reason
from app.services.diagnostic_outcomes import _FIELD_LABEL_RE, _job_reason_text, reason_category

REVIEW_STATUSES = ("FAILED", "NEEDS_REVIEW", "MANUAL_REVIEW")
SENT_STATUSES = frozenset({"SUBMITTED", "REJECTED", "SUBMISSION_UNKNOWN"})

KIND_CODE = "code"  # a code fix could unblock it
KIND_USER_INPUT = "needs-user-input"  # waiting on the candidate's answers
KIND_CLASSIFIED = "classified"  # the queue decided it is ineligible / manual-only
KIND_NOT_CODE = "not-code-fixable"  # bot walls, policy, employer requirements

# category -> (likelihood a single shared fix works, rough effort in hours).
# Priors, deliberately coarse: they only order groups of similar size. A
# category missing here is "Other" territory and gets the weakest prior.
_CODE_PRIORS: dict[str, tuple[float, float]] = {
    "Required field left blank in the browser DOM": (0.6, 1.0),
    "Unhandled automation exception": (0.5, 1.5),
    "Browser page or frame closed mid-run": (0.4, 1.0),
    "Browser navigation timed out": (0.3, 1.0),
    "No application form on the posting page": (0.35, 1.5),
    "Resume tailoring fell back to the template": (0.4, 1.0),
    "Resume not usefully tailored": (0.3, 1.5),
    "No reason recorded": (0.2, 1.0),
}
_WATCHDOG_PRIOR = (0.4, 1.5)
_OTHER_PRIOR = (0.2, 2.0)

# Reasons no code change in this repository should "fix": the employer, the
# candidate's policy, or a protection the system must not bypass.
_NOT_CODE_CATEGORIES = frozenset({
    "Roblox refuses automated browsers (apply by hand)",
    "Okta reCAPTCHA (known bot-protected)",
    "Cover letter required by employer",
    "Blocked by reCAPTCHA",
    "Blocked by DataDome",
    "Blocked by hCaptcha",
    "Workday requires a candidate account",
    "Tier-1 company — reserved for hand-written application",
    "Defense/ITAR contractor (excluded per preference)",
    "Location outside the United States",
    "Internship (excluded)",
    "Requires U.S. citizenship / clearance / no sponsorship",
    "Duplicate — already applied to this posting",
    "Second-opinion match gate did not approve",
    "Match score below the submit bar after tailoring",
    "Non-SWE role (title filter)",
    "Submission could not be verified",
    "Greenhouse emailed-security-code step",
    "Persistent contradiction block",
    "Posting expired or unlisted",
    "Material contradiction with profile",
})
_ACCOUNT_RE = re.compile(r"requires a candidate account", re.I)
_EXPIRED_CATEGORIES = frozenset({"Posting expired or unlisted"})
_EXCLUDED_CLASSIFICATIONS = {
    "POSTING_EXPIRED": "expired",
    "NOT_A_REAL_POSTING": "expired",
    "DUPLICATE_APPLICATION": "duplicate",
}
_SEVERITY = {"FAILED": 1.0, "NEEDS_REVIEW": 0.8, "MANUAL_REVIEW": 0.6}

_ATS_HOSTS = (
    ("greenhouse", "greenhouse"),
    ("lever.co", "lever"),
    ("ashbyhq", "ashby"),
    ("myworkdayjobs", "workday"),
    ("workday", "workday"),
    ("smartrecruiters", "smartrecruiters"),
    ("icims", "icims"),
    ("jobvite", "jobvite"),
    ("bamboohr", "bamboohr"),
    ("workable", "workable"),
    ("rippling", "rippling"),
    ("gem.com", "gem"),
)


def ats_of(job: dict[str, Any]) -> str:
    host = urlsplit(str(job.get("applicationUrl") or job.get("url") or "").strip().lower()).netloc
    if not host:
        return "unknown"
    for needle, name in _ATS_HOSTS:
        if needle in host:
            return name
    parts = host.split(":")[0].split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def normalise_label(label: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", (label or "").lower())
    text = re.sub(r"\b(required|optional)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:60] or "unlabelled"


def _other_key(reason: str) -> str:
    """A stable key for an unrecognised reason: drop ids, numbers and quotes."""
    text = re.sub(r"'[^']*'|\"[^\"]*\"", "'…'", reason or "")
    text = re.sub(r"\b[0-9a-f]{8,}\b|\d+", "#", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()[:70] or "empty"


def classify(job: dict[str, Any]) -> tuple[str, str, str]:
    """(kind, signature, category) for one stuck job."""
    ats = ats_of(job)
    if job.get("pendingQuestions"):
        return KIND_USER_INPUT, f"needs-user-input|{ats}", "Waiting on your answers"
    classified = str(job.get("ineligibilityReason") or "").strip()
    if classified:
        return KIND_CLASSIFIED, f"classified:{classified}|{ats}", classified
    category = reason_category(job)
    reason = _job_reason_text(job)
    if category == "Required field left blank in the browser DOM":
        match = _FIELD_LABEL_RE.search(reason)
        label = normalise_label(match.group(1)) if match else "unlabelled"
        return KIND_CODE, f"{category}|{ats}|{label}", category
    if category in _NOT_CODE_CATEGORIES:
        return KIND_NOT_CODE, f"{category}|{ats}", category
    if _ACCOUNT_RE.search(reason):
        # Creating an employer account needs the candidate's authorization; no code fix applies.
        return KIND_NOT_CODE, f"Candidate account required|{ats}", "Candidate account required"
    if category == "Other":
        return KIND_CODE, f"Other|{ats}|{_other_key(reason)}", category
    return KIND_CODE, f"{category}|{ats}", category


def exclusion_reason(job: dict[str, Any], sent_urls: set[str]) -> str | None:
    """Why a job must not count toward (or be requeued for) its group."""
    status = str(job.get("status") or "")
    if status not in REVIEW_STATUSES:
        return "not-stuck"
    if requeue_refusal_reason(job):
        return "may-be-submitted"
    classified = str(job.get("ineligibilityReason") or "")
    if classified in _EXCLUDED_CLASSIFICATIONS:
        return _EXCLUDED_CLASSIFICATIONS[classified]
    if classified:
        return "ineligible"
    if reason_category(job) in _EXPIRED_CATEGORIES:
        return "expired"
    url = canonical_application_url(job.get("applicationUrl") or job.get("url"))
    if url and url in sent_urls:
        return "duplicate"
    return None


@dataclass
class Group:
    signature: str
    kind: str
    category: str
    ats: str
    eligible_ids: list[str] = field(default_factory=list)
    excluded: dict[str, int] = field(default_factory=dict)
    statuses: dict[str, int] = field(default_factory=dict)
    sample_reason: str = ""
    likelihood: float = 0.0
    effort_hours: float = 1.0
    severity: float = 0.0
    score: float = 0.0
    attempts: int = 0
    blocked: bool = False

    @property
    def eligible(self) -> int:
        return len(self.eligible_ids)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["eligible"] = self.eligible
        out["eligibleIds"] = out.pop("eligible_ids")[:500]
        return out


def _priors(kind: str, category: str) -> tuple[float, float]:
    if kind != KIND_CODE:
        return 0.0, 0.0
    if category.startswith("Watchdog timeout"):
        return _WATCHDOG_PRIOR
    return _CODE_PRIORS.get(category, _OTHER_PRIOR)


def build_groups(
    jobs: Iterable[dict[str, Any]],
    history: dict[str, dict[str, Any]] | None = None,
    max_attempts: int = 2,
) -> list[Group]:
    """Group, count and rank. `history` maps signature -> {attempts, blocked}."""
    history = history or {}
    jobs = list(jobs)
    sent_urls = {
        canonical_application_url(j.get("applicationUrl") or j.get("url"))
        for j in jobs
        if str(j.get("status") or "") in SENT_STATUSES
    }
    sent_urls.discard("")

    groups: dict[str, Group] = {}
    severity_sum: dict[str, float] = {}
    for job in jobs:
        status = str(job.get("status") or "")
        if status not in REVIEW_STATUSES:
            continue
        kind, signature, category = classify(job)
        group = groups.get(signature)
        if group is None:
            group = groups[signature] = Group(
                signature=signature,
                kind=kind,
                category=category,
                ats=ats_of(job),
                sample_reason=_job_reason_text(job)[:300],
            )
        group.statuses[status] = group.statuses.get(status, 0) + 1
        excluded = exclusion_reason(job, sent_urls)
        if excluded is None and kind == KIND_CLASSIFIED:
            excluded = "ineligible"
        if excluded:
            group.excluded[excluded] = group.excluded.get(excluded, 0) + 1
            continue
        group.eligible_ids.append(str(job.get("id")))
        severity_sum[signature] = severity_sum.get(signature, 0.0) + _SEVERITY.get(status, 0.5)

    for group in groups.values():
        group.likelihood, group.effort_hours = _priors(group.kind, group.category)
        group.severity = round(severity_sum.get(group.signature, 0.0) / group.eligible, 3) if group.eligible else 0.0
        past = history.get(group.signature) or {}
        group.attempts = int(past.get("attempts") or 0)
        group.blocked = bool(past.get("blocked")) or group.attempts >= max_attempts
        if group.kind == KIND_CODE and group.eligible and not group.blocked:
            group.score = round(group.eligible * group.likelihood * group.severity / max(group.effort_hours, 0.25), 3)

    return sorted(groups.values(), key=lambda g: (-g.score, -g.eligible, g.signature))


def next_fixable(groups: list[Group], min_eligible: int = 2) -> Group | None:
    """The largest recoverable group worth one bounded fix, if any."""
    for group in groups:
        if group.kind == KIND_CODE and not group.blocked and group.eligible >= min_eligible and group.score > 0:
            return group
    return None


def requeue_candidates(jobs: Iterable[dict[str, Any]], signature: str) -> list[dict[str, Any]]:
    """Jobs to requeue once the fix for `signature` is live.

    Re-derived from a fresh read, never from the stored group: a job that moved,
    got answered, was submitted by hand or changed reason since grouping is not
    requeued on the strength of an old signature.
    """
    jobs = list(jobs)
    sent_urls = {
        canonical_application_url(j.get("applicationUrl") or j.get("url"))
        for j in jobs
        if str(j.get("status") or "") in SENT_STATUSES
    }
    sent_urls.discard("")
    out = []
    for job in jobs:
        if str(job.get("status") or "") not in REVIEW_STATUSES:
            continue
        kind, sig, _category = classify(job)
        if sig != signature or kind != KIND_CODE:
            continue
        if exclusion_reason(job, sent_urls):
            continue
        out.append(job)
    return out
