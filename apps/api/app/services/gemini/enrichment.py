"""The four things CareerOS asks Gemini to do, and what happens when it cannot.

Every function here returns a dataclass with an `available` flag. `available`
is False whenever Gemini did not produce a usable answer - disabled, rate
limited, circuit open, malformed, or answered with something that failed the
grounding check - and in every case the caller carries on with its
deterministic path. No function here raises, and none of them is on a path that
CareerOS needs to complete a run.

The Gemini result is always kept separate from the deterministic one rather
than overwriting it. That is what makes it possible to answer "is Gemini
actually improving decisions" later, instead of having to take it on faith.

What Gemini is *not* used for is as important as what it is used for. It is
never asked for a name, an email address, a phone number, a work-authorisation
answer, a demographic answer or a location: those are profile lookups with a
right answer, and a language model can only make them worse. `question_is_eligible`
enforces that structurally - the deterministic types are refused before a
request is ever built, so there is no configuration under which a name goes to
a cloud model.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.gemini import schemas
from app.services.gemini.ambiguity import Uncertainty
from app.services.gemini.gateway import GeminiRequest, Priority, get_gateway
from app.services.gemini.grounding import Corpus, build_corpus, check, load_default_corpus
from app.services.gemini.telemetry import telemetry

logger = logging.getLogger("careeros.gemini.enrichment")

TASK_QUESTION = "application_question"
TASK_TAILORING = "resume_tailoring"
TASK_MATCH = "ambiguous_match"
TASK_TEACHER = "benchmark_label"


def normalized_hash(text: str, limit: int = 12000) -> str:
    """A stable fingerprint for a job description, insensitive to whitespace.

    Postings are re-scraped constantly and come back with different line
    wrapping and boilerplate spacing for identical content. Hashing the raw
    text would treat each re-scrape as a new posting and pay for the same
    judgement again.
    """
    collapsed = re.sub(r"\s+", " ", (text or "").strip().lower())[:limit]
    return hashlib.sha256(collapsed.encode("utf-8", "ignore")).hexdigest()[:24]


def _evidence_corpus(
    profile: dict[str, Any] | None = None,
    *,
    resume_text: str = "",
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
) -> Corpus:
    """What the candidate can evidence, for grounding and for the prompt itself.

    A caller that hands over its own material gets a corpus built from exactly
    that. A caller that hands over nothing - which is every call from inside the
    Playwright worker, where only the question is in scope - gets the
    candidate's whole verified evidence base rather than an empty one.

    The distinction matters because the corpus is both the grounding guard and
    the only source of facts in the prompt. Too narrow and Gemini is asked to
    answer from a two-page summary and then judged against it, which rejects
    true sentences and quietly turns the layer off.
    """
    if profile or resume_text or documents or accomplishments:
        return build_corpus(
            profile, resume_text=resume_text,
            documents=documents, accomplishments=accomplishments,
        )
    return load_default_corpus()


# ── 1. Application questions ─────────────────────────────────────────────────

#: Free-text intents Gemini may answer. Everything else is either a profile
#: lookup or a question with a right answer that must not be generated.
_ELIGIBLE_FREE_TEXT_PREFIX = "FREE_TEXT_"
_ELIGIBLE_EXTRA_TYPES = {"COMPANY_FAMILIARITY", "OTHER", "UNKNOWN"}


@dataclass
class AnswerEnrichment:
    available: bool = False
    answer: str = ""
    confidence: float = 0.0
    supported: bool = False
    evidence: list[str] = field(default_factory=list)
    reason: str = ""
    outcome: str = ""
    grounded: bool = False
    cached: bool = False


def question_is_eligible(
    question: str,
    *,
    canonical_key: str = "",
    options: list[str] | None = None,
) -> tuple[bool, str]:
    """May this question go to Gemini at all? Returns (eligible, why not).

    Refuses, in order: anything with a deterministic canonical key, anything
    with a fixed set of options (a choice is a lookup, not prose), and anything
    the classifier recognises as a factual or sensitive field.
    """
    if canonical_key.strip():
        return False, f"deterministic profile field ({canonical_key})"
    if options:
        return False, "question offers fixed options; answered deterministically"
    if not (question or "").strip():
        return False, "empty question"

    try:
        from app.services.application_assistant.question_classifier import (
            classify_question,
            is_sensitive_factual,
        )

        qtype = classify_question(question)
        if is_sensitive_factual(qtype):
            return False, f"sensitive factual field ({qtype.value})"
        name = qtype.value
        if name.startswith(_ELIGIBLE_FREE_TEXT_PREFIX) or name in _ELIGIBLE_EXTRA_TYPES:
            return True, ""
        # A recognised non-free-text type (salary, notice period, GPA, degree,
        # years of experience) has a right answer that lives in the profile.
        # Generating one is the failure mode this whole layer exists to avoid.
        return False, f"factual field answered from the profile ({name})"
    except Exception:  # noqa: BLE001 - classifier problems must not open the gate
        logger.debug("Question classification failed; refusing Gemini", exc_info=True)
        return False, "question could not be classified"


async def answer_application_question(
    question: str,
    *,
    profile: dict[str, Any] | None = None,
    resume_text: str = "",
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
    company: str = "",
    role: str = "",
    job_description: str = "",
    canonical_key: str = "",
    options: list[str] | None = None,
    corpus: Corpus | None = None,
    active_application: bool = False,
) -> AnswerEnrichment:
    """A grounded answer to one open-ended application question.

    `active_application` raises the priority to the top of the queue: an
    application sitting in an employer's form with a half-filled textarea is the
    only thing in CareerOS that a person is actually waiting on.
    """
    eligible, why_not = question_is_eligible(question, canonical_key=canonical_key, options=options)
    if not eligible:
        return AnswerEnrichment(available=False, reason=why_not, outcome="ineligible")

    evidence_corpus = corpus or _evidence_corpus(
        profile, resume_text=resume_text, documents=documents, accomplishments=accomplishments
    )
    if evidence_corpus.empty:
        return AnswerEnrichment(
            available=False, outcome="ineligible",
            reason="no candidate resume or profile text to ground an answer in",
        )

    prompt = (
        f"## Role\n{role or 'Not stated'} at {company or 'the employer'}\n\n"
        f"## Job description (context only; never a source of candidate facts)\n"
        f"{(job_description or 'Not provided')[:3000]}\n\n"
        f"## Candidate material (the ONLY source of facts about the candidate)\n"
        f"{evidence_corpus.text[:9000]}\n\n"
        f"## Question\n{question.strip()}\n"
    )

    result = await get_gateway().submit(GeminiRequest(
        task=TASK_QUESTION,
        system=schemas.APPLICATION_QUESTION_SYSTEM,
        prompt=prompt,
        schema=schemas.APPLICATION_QUESTION_SCHEMA,
        schema_name="application_answer",
        prompt_version=schemas.APPLICATION_QUESTION_VERSION,
        priority=Priority.ACTIVE_APPLICATION if active_application else Priority.APPLICATION_QUESTION,
        # The corpus version is in the key but the corpus text is truncated in
        # the prompt, so a resume edit past the truncation point still
        # invalidates. The JD hash keeps answers per-posting.
        cache_parts=(evidence_corpus.version, normalized_hash(job_description)),
        max_tokens=600,
        deadline_seconds=90.0 if active_application else 150.0,
    ))

    if not result.ok or not result.data:
        telemetry.record_fallback(TASK_QUESTION)
        return AnswerEnrichment(available=False, outcome=result.outcome.value, reason=result.detail)

    data = result.data
    answer = str(data.get("answer") or "").strip()
    if not data.get("supported") or not answer:
        # Gemini declining to answer is a success for this layer: it means the
        # grounding rules held. The caller still falls back, but nothing failed.
        return AnswerEnrichment(
            available=False, outcome="insufficient_evidence",
            reason=str(data.get("reason") or "Gemini reported insufficient evidence"),
            confidence=float(data.get("confidence") or 0.0),
        )

    verdict = check(answer, evidence_corpus)
    if not verdict.ok:
        telemetry.record_fallback(TASK_QUESTION)
        logger.warning(
            "Gemini answer rejected for %r: %s", question[:60], verdict.reason
        )
        return AnswerEnrichment(
            available=False, outcome="ungrounded",
            reason=f"answer was not supported by the candidate corpus ({verdict.reason})",
        )

    return AnswerEnrichment(
        available=True,
        answer=answer,
        confidence=float(data.get("confidence") or 0.0),
        supported=True,
        evidence=[str(item) for item in (data.get("evidence") or [])][:6],
        reason=str(data.get("reason") or ""),
        outcome=result.outcome.value,
        grounded=True,
        cached=result.cached,
    )


# ── 2. Resume tailoring ──────────────────────────────────────────────────────

@dataclass
class TailoringEnrichment:
    available: bool = False
    #: Original index -> rewritten bullet. Only bullets that changed and passed
    #: the fabrication guard appear here; everything else keeps its original.
    bullets: dict[int, str] = field(default_factory=dict)
    rejected: list[int] = field(default_factory=list)
    outcome: str = ""
    reason: str = ""
    cached: bool = False


async def tailor_bullets(
    bullets: list[str],
    *,
    job_description: str,
    job_title: str = "",
    company: str = "",
    corpus: Corpus | None = None,
    start_index: int = 0,
) -> TailoringEnrichment:
    """Re-word existing resume bullets toward a posting. Selection, not authorship.

    Every returned bullet passes back through the same fabrication guard the
    local-model path uses, so a rewrite that invents a figure is discarded here
    exactly as it would be there. Gemini gets no special trust for being bigger.
    """
    if not bullets:
        return TailoringEnrichment(available=False, outcome="ineligible", reason="no bullets given")

    numbered = "\n".join(
        f"[{start_index + offset}] {text}" for offset, text in enumerate(bullets)
    )
    prompt = (
        f"## Target role\n{job_title or 'Not stated'} at {company or 'the employer'}\n\n"
        f"## Job description\n{(job_description or 'Not provided')[:5000]}\n\n"
        f"## Resume bullets to re-word (return every one, keeping its index)\n{numbered}\n"
    )

    result = await get_gateway().submit(GeminiRequest(
        task=TASK_TAILORING,
        system=schemas.RESUME_TAILORING_SYSTEM,
        prompt=prompt,
        schema=schemas.RESUME_TAILORING_SCHEMA,
        schema_name="tailored_bullets",
        prompt_version=schemas.RESUME_TAILORING_VERSION,
        priority=Priority.RESUME_TAILORING,
        cache_parts=(normalized_hash(job_description), normalized_hash("\n".join(bullets))),
        max_tokens=1600,
        deadline_seconds=150.0,
    ))

    if not result.ok or not result.data:
        telemetry.record_fallback(TASK_TAILORING)
        return TailoringEnrichment(available=False, outcome=result.outcome.value, reason=result.detail)

    from app.services.application_assistant.resume_diff_service import _reject_fabrication

    accepted: dict[int, str] = {}
    rejected: list[int] = []
    for entry in result.data.get("bullets") or []:
        try:
            index = int(entry.get("index"))
            text = str(entry.get("text") or "").strip()
        except (TypeError, ValueError):
            continue
        offset = index - start_index
        if not text or not (0 <= offset < len(bullets)):
            continue
        original = bullets[offset]
        if not entry.get("changed") or text == original:
            continue
        # The guard returns the original when the rewrite is unsafe, which is
        # exactly the signal needed: unchanged means rejected.
        safe = _reject_fabrication(text, original)
        if safe == original:
            rejected.append(index)
            continue
        accepted[index] = safe

    if not accepted:
        telemetry.record_fallback(TASK_TAILORING)
        return TailoringEnrichment(
            available=False, outcome="ungrounded", rejected=rejected,
            reason="no rewrite survived the fabrication guard",
        )

    return TailoringEnrichment(
        available=True, bullets=accepted, rejected=rejected,
        outcome=result.outcome.value, cached=result.cached,
    )


# ── 3. Ambiguous job matching ────────────────────────────────────────────────

@dataclass
class MatchEnrichment:
    available: bool = False
    decision: str = ""
    primary_role_family: str = ""
    secondary_role_family: str = ""
    seniority_match: bool = False
    critical_mismatch: bool = False
    critical_requirements: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    outcome: str = ""
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Stored beside - never instead of - the deterministic match result."""
        return {
            "source": "gemini",
            "decision": self.decision,
            "primaryRoleFamily": self.primary_role_family,
            "secondaryRoleFamily": self.secondary_role_family,
            "seniorityMatch": self.seniority_match,
            "criticalMismatch": self.critical_mismatch,
            "criticalRequirements": self.critical_requirements,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "cached": self.cached,
        }


async def clarify_match(
    job: dict[str, Any],
    uncertainty: Uncertainty,
    *,
    corpus: Corpus | None = None,
    profile: dict[str, Any] | None = None,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
) -> MatchEnrichment:
    """A second opinion on a posting the deterministic matcher could not settle.

    Only called for postings `ambiguity.assess` flagged. The result never
    replaces the deterministic score - the caller stores it alongside, and a
    failure here means the posting goes to review rather than the run failing.
    """
    if not uncertainty.ambiguous:
        return MatchEnrichment(available=False, outcome="not_ambiguous")

    description = str(job.get("description") or job.get("snippet") or "")
    evidence_corpus = corpus or _evidence_corpus(
        profile, documents=documents, accomplishments=accomplishments
    )

    prompt = (
        f"## Candidate\n{evidence_corpus.text[:6000] or 'No candidate material available.'}\n\n"
        f"## Posting\n{job.get('title') or 'Unknown role'} at {job.get('company') or 'unknown company'}\n"
        f"{description[:9000]}\n\n"
        f"## Why this needs a second opinion\n"
        + "\n".join(f"- {reason}" for reason in uncertainty.reasons)
    )

    result = await get_gateway().submit(GeminiRequest(
        task=TASK_MATCH,
        system=schemas.AMBIGUOUS_MATCH_SYSTEM,
        prompt=prompt,
        schema=schemas.AMBIGUOUS_MATCH_SCHEMA,
        schema_name="match_clarification",
        prompt_version=schemas.AMBIGUOUS_MATCH_VERSION,
        priority=Priority.AMBIGUOUS_MATCH,
        cache_parts=(evidence_corpus.version, normalized_hash(description)),
        max_tokens=700,
        deadline_seconds=120.0,
    ))

    if not result.ok or not result.data:
        telemetry.record_fallback(TASK_MATCH)
        return MatchEnrichment(available=False, outcome=result.outcome.value, reason=result.detail)

    data = result.data
    return MatchEnrichment(
        available=True,
        decision=str(data.get("decision") or "REVIEW").upper(),
        primary_role_family=str(data.get("primary_role_family") or ""),
        secondary_role_family=str(data.get("secondary_role_family") or ""),
        seniority_match=bool(data.get("seniority_match")),
        critical_mismatch=bool(data.get("critical_mismatch")),
        critical_requirements=[str(item) for item in (data.get("critical_requirements") or [])][:8],
        confidence=float(data.get("confidence") or 0.0),
        reason=str(data.get("reason") or "")[:400],
        outcome=result.outcome.value,
        cached=result.cached,
    )


# ── 4. Offline benchmark labelling ───────────────────────────────────────────

@dataclass
class TeacherLabel:
    available: bool = False
    decision: str = ""
    primary_role_family: str = ""
    secondary_role_family: str = ""
    seniority_match: bool = False
    critical_mismatch: bool = False
    confidence: float = 0.0
    reason: str = ""
    redactions: int = 0
    cached: bool = False
    outcome: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            # Never "human". A label produced by a model is a model's label, and
            # calling it anything else would corrupt every evaluation that
            # treats human labels as ground truth.
            "label_source": "gemini_teacher",
            "decision": self.decision,
            "primary_role_family": self.primary_role_family,
            "secondary_role_family": self.secondary_role_family,
            "seniority_match": self.seniority_match,
            "critical_mismatch": self.critical_mismatch,
            "confidence": self.confidence,
            "reason": self.reason,
            "redactions": self.redactions,
        }


async def label_posting(
    resume_summary: str,
    title: str,
    body: str,
    *,
    strip_title: Any = None,
) -> TeacherLabel:
    """Label one posting for MatchLab, with the job title hidden.

    The title removal is the whole point. Bootstrap labels were derived from job
    titles and the winning scorer read job titles, so its 0.945 AUC was partly
    reconstructing its own labeller - title-only scored *higher* than
    title+body, which only happens when the label is a function of the title.
    A teacher that cannot see the title cannot recreate that.

    Runs at the lowest priority and may wait out a circuit cooldown, because
    nothing is blocked on it. It must never delay an application.
    """
    if strip_title is None:
        from app.services.gemini.title_redaction import strip_title as strip_title_impl

        strip_title = strip_title_impl

    redacted, redactions = strip_title(title, body)
    prompt = (
        f"CANDIDATE\n{resume_summary[:6000]}\n\n"
        f"JOB DESCRIPTION (title deliberately withheld)\n{redacted[:9000]}\n\n"
        f"[{redactions} title mention(s) were redacted from this description]"
    )

    result = await get_gateway().submit(GeminiRequest(
        task=TASK_TEACHER,
        system=schemas.TEACHER_SYSTEM,
        prompt=prompt,
        schema=schemas.TEACHER_SCHEMA,
        schema_name="job_fit",
        prompt_version=schemas.TEACHER_VERSION,
        priority=Priority.BENCHMARK_LABEL,
        max_tokens=600,
        # Offline work waits for capacity instead of failing, and waits behind
        # everything else. A benchmark run must never be the reason an
        # application did not get its answer.
        wait_for_circuit=True,
        deadline_seconds=1800.0,
    ))

    if not result.ok or not result.data:
        return TeacherLabel(available=False, outcome=result.outcome.value, reason=result.detail)

    data = result.data
    return TeacherLabel(
        available=True,
        decision=str(data.get("decision") or "").upper(),
        primary_role_family=str(data.get("primary_role_family") or "other"),
        secondary_role_family=str(data.get("secondary_role_family") or ""),
        seniority_match=bool(data.get("seniority_match")),
        critical_mismatch=bool(data.get("critical_mismatch")),
        confidence=float(data.get("confidence") or 0.0),
        reason=str(data.get("reason") or "")[:400],
        redactions=redactions,
        cached=result.cached,
        outcome=result.outcome.value,
    )
