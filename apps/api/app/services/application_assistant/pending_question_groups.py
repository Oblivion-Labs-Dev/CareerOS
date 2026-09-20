"""One question, answered once, unblocking every application that asks it.

Fifty Roblox postings can stall on the same screening question. Answering it
fifty times is not review, it is data entry, and it is the reason a review queue
of 872 jobs feels unworkable.

The machinery to avoid that already exists and is not being surfaced: a saved
answer goes into the answer library, and ``_find_user_approved_answer`` matches
it against later questions by **word overlap**, not exact text — deliberately, because
the same underlying field comes back worded differently from attempt to attempt.
So one saved answer already propagates. Nothing ever told the user that, or
showed them which single answer would clear the most work.

This module groups the outstanding questions so it can.

**The grouping must use the same matcher the resolver uses.** That is the whole
correctness property here: if these groups were built with different logic than
``_find_user_approved_answer`` applies at fill time, the count shown next to a
question ("unblocks 50 applications") would be a number the system cannot
honour. So both sides share ``_significant_words`` and the same 0.5 overlap
threshold, and a change to one must move the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from app.services.application_assistant.profile_answer_resolver import (
    _significant_words,
)

#: Same threshold `_find_user_approved_answer` applies when deciding whether a
#: saved answer covers a question. Grouping more loosely than this would promise
#: an unblock that never happens; more tightly would split one question into
#: several rows the user answers repeatedly.
OVERLAP_THRESHOLD = 0.5


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left | right), 1)


@dataclass
class QuestionGroup:
    """One distinct question, and every application waiting on it."""

    #: The wording shown to the user. The longest variant is used, on the
    #: grounds that a truncated or abbreviated rendering of a question is
    #: harder to answer correctly than a complete one.
    question: str
    field_type: str = "text"
    options: list[str] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)
    job_ids: list[str] = field(default_factory=list)
    companies: dict[str, int] = field(default_factory=dict)
    #: Applications for which this is the *only* outstanding question, so
    #: answering it alone finishes them. Always <= job_count.
    #:
    #: Both numbers are carried because only this one is a promise the system
    #: can keep. Measured on the live queue, the twenty most-asked questions are
    #: asked by 185 applications but single-handedly finish only 54 of them: the
    #: median application is waiting on two questions, and one has 36. Showing
    #: "unblocks 185" next to a question would be the kind of inflated claim
    #: this codebase refuses to make elsewhere.
    solo_job_ids: list[str] = field(default_factory=list)
    _words: set[str] = field(default_factory=set, repr=False)

    @property
    def job_count(self) -> int:
        return len(self.job_ids)

    @property
    def unblocks_alone(self) -> int:
        return len(self.solo_job_ids)

    @property
    def company_count(self) -> int:
        return len(self.companies)

    def headline(self) -> str:
        """How much work this one answer clears, stated honestly.

        Names both numbers when they differ, because the gap between them is
        the useful information: a question asked by forty applications that
        finishes none of them on its own is a very different piece of work from
        one that finishes twelve.
        """
        jobs = f"{self.job_count} application{'' if self.job_count == 1 else 's'}"
        where = (
            f"at {next(iter(self.companies))}"
            if self.company_count == 1
            else f"across {self.company_count} companies"
        )
        if self.unblocks_alone == self.job_count:
            return f"Finishes {jobs} {where}"
        if self.unblocks_alone:
            return f"Asked by {jobs} {where} — finishes {self.unblocks_alone} on its own"
        return f"Asked by {jobs} {where} — each still needs other answers too"

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "fieldType": self.field_type,
            "options": list(self.options),
            "variants": list(self.variants),
            "jobIds": list(self.job_ids),
            "jobCount": self.job_count,
            "unblocksAlone": self.unblocks_alone,
            "soloJobIds": list(self.solo_job_ids),
            "companies": [
                {"company": name, "count": count}
                for name, count in sorted(self.companies.items(), key=lambda kv: -kv[1])
            ],
            "companyCount": self.company_count,
            "headline": self.headline(),
        }


def _pending_entries(job: dict[str, Any]) -> list[dict[str, Any]]:
    """The outstanding questions recorded on a job.

    `pendingQuestions` is what the executor actually writes (via
    error_normalizer.build_pending_questions). `unresolvedQuestions` is
    vestigial — nothing in the service layer populates it — but it is read here
    too so that any older row still surfaces rather than silently contributing
    nothing.
    """
    entries: list[dict[str, Any]] = []
    for key in ("pendingQuestions", "unresolvedQuestions"):
        value = job.get(key)
        if isinstance(value, list):
            entries.extend(item for item in value if isinstance(item, dict))
    return entries


def group_pending_questions(
    jobs: Iterable[dict[str, Any]],
    *,
    threshold: float = OVERLAP_THRESHOLD,
) -> list[QuestionGroup]:
    """Collapse every outstanding question into one row per distinct question.

    Ordered by how many applications each unblocks, because that is the order
    worth working through: the top row is always the best use of the next
    minute.
    """
    groups: list[QuestionGroup] = []

    for job in jobs:
        job_id = str(job.get("id") or "")
        company = str(job.get("company") or "Unknown").strip() or "Unknown"

        for entry in _pending_entries(job):
            text = str(entry.get("question") or entry.get("rawLabel") or "").strip()
            if not text:
                continue
            words = _significant_words(text)
            if not words:
                continue

            match = None
            best = threshold
            for group in groups:
                score = _overlap(words, group._words)
                if score >= best:
                    best = score
                    match = group

            if match is None:
                match = QuestionGroup(
                    question=text,
                    field_type=str(entry.get("fieldType") or "text"),
                    options=list(entry.get("options") or []),
                    _words=words,
                )
                groups.append(match)
            else:
                # Keep the fullest wording and the richest option list seen for
                # this question - a later job may have captured the complete
                # form of a question an earlier one truncated.
                if len(text) > len(match.question):
                    match.question = text
                if not match.options and entry.get("options"):
                    match.options = list(entry["options"])

            if text not in match.variants:
                match.variants.append(text)
            if job_id and job_id not in match.job_ids:
                match.job_ids.append(job_id)
                match.companies[company] = match.companies.get(company, 0) + 1

    # Second pass: which applications does each question finish by itself?
    # An application is only done when every question it asks has an answer, so
    # this is the count that can honestly be promised.
    blockers_per_job: dict[str, int] = {}
    for group in groups:
        for job_id in group.job_ids:
            blockers_per_job[job_id] = blockers_per_job.get(job_id, 0) + 1
    for group in groups:
        group.solo_job_ids = [
            job_id for job_id in group.job_ids if blockers_per_job.get(job_id) == 1
        ]

    # Ordered by what finishes the most work first, falling back to how widely
    # the question is asked. Sorting on job_count alone would put a question
    # asked by forty applications above one that actually completes twelve.
    groups.sort(key=lambda g: (-g.unblocks_alone, -g.job_count, g.question))
    return groups


def answer_question_group(
    db: Any,
    *,
    question: str,
    answer: str,
    variants: list[str] | None = None,
    job_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Record one answer, then release every application it finishes.

    Three things happen, in this order:

    1. **The answer is saved once**, to the answer library, carrying every
       wording the question was seen in. That is what makes it apply to jobs
       beyond the ones listed here and to postings not yet attempted —
       ``_find_user_approved_answer`` matches saved entries by word overlap, so
       a later rephrasing still finds it.
    2. **Each affected job records the answer** and drops the question from its
       pending list.
    3. **Only jobs with nothing left pending are requeued.** An application with
       two blockers is not finished by answering one of them, and moving it back
       to the queue would spend a browser run to rediscover the second. Jobs
       still holding other questions stay where they are and are reported back
       as ``stillBlocked``.
    """
    from app.db.store import new_id, now_iso
    from app.services.application_assistant.persistence import (
        get_autopilot_job,
        save_autopilot_job,
        upsert_answer,
    )

    question = (question or "").strip()
    answer = (answer or "").strip()
    if not question or not answer:
        raise ValueError("Both a question and an answer are required.")

    wordings = [w for w in ([question] + list(variants or [])) if str(w or "").strip()]
    seen: set[str] = set()
    unique_wordings = [w for w in wordings if not (w.lower() in seen or seen.add(w.lower()))]

    upsert_answer(db, {
        "id": new_id("lib_"),
        "normalizedKey": question.lower(),
        # Every wording seen, so a later rephrasing of the same underlying
        # field matches this entry rather than asking the candidate again.
        "questionVariants": unique_wordings,
        "answerType": "short_text",
        "value": answer,
        "verificationStatus": "verified",
        "source": "user_approved_group",
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    })

    target_words = _significant_words(question)
    requeued: list[str] = []
    still_blocked: list[str] = []

    for job_id in job_ids or []:
        job = get_autopilot_job(db, job_id)
        if not job:
            continue

        remaining = [
            entry for entry in (job.get("pendingQuestions") or [])
            if _overlap(
                _significant_words(str(entry.get("question") or entry.get("rawLabel") or "")),
                target_words,
            ) < OVERLAP_THRESHOLD
        ]
        job["pendingQuestions"] = remaining
        job.setdefault("customAnswers", {})[question] = answer

        if remaining:
            still_blocked.append(job_id)
            save_autopilot_job(db, job)
            continue

        # Nothing left outstanding: this one can be attempted again. Clearing
        # the persistent block matches the single-job approve path - a verified
        # answer is precisely what that block was waiting for.
        job.pop("hasPersistentBlock", None)
        job.pop("blockingContradictions", None)
        job["previousStatus"] = job.get("status")
        job["status"] = "QUEUED"
        job["queuedAt"] = now_iso()
        job["lastError"] = None
        job["lastErrorType"] = None
        job["attemptCount"] = 0
        save_autopilot_job(db, job)
        requeued.append(job_id)

    return {
        "question": question,
        "answer": answer,
        "requeued": requeued,
        "requeuedCount": len(requeued),
        "stillBlocked": still_blocked,
        "stillBlockedCount": len(still_blocked),
        "message": (
            f"Answer saved. {len(requeued)} application"
            f"{'' if len(requeued) == 1 else 's'} returned to the queue"
            + (
                f"; {len(still_blocked)} still waiting on other questions."
                if still_blocked
                else "."
            )
        ),
    }


def summarise(groups: list[QuestionGroup]) -> dict[str, Any]:
    """Headline numbers for the review panel."""
    total_jobs = len({job_id for group in groups for job_id in group.job_ids})
    quick_wins = sum(group.unblocks_alone for group in groups)
    return {
        "groups": [group.to_dict() for group in groups],
        "questionCount": len(groups),
        "blockedJobCount": total_jobs,
        #: Applications waiting on exactly one question. These are the ones a
        #: single answer finishes, and the only ones worth promising.
        "singleAnswerJobCount": quick_wins,
        "headline": (
            f"{len(groups)} distinct question{'' if len(groups) == 1 else 's'} "
            f"{'is' if len(groups) == 1 else 'are'} holding {total_jobs} "
            f"application{'' if total_jobs == 1 else 's'}. "
            f"{quick_wins} of those need only one answer."
        ),
    }
