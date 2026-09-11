"""Score the resume that will actually be submitted, not the one on file.

``generate_role_tailoring_diff`` used to report ``matchScore`` by reading the
job row's stored score straight back out (``job_match_score(job)``). That number
describes the *untailored* resume, so it could not move no matter what tailoring
produced: a retry loop built on it would re-tailor forever and compare the same
figure to the same bar, and ``matchScoreAtSubmission`` recorded a score for a
document that was never submitted.

This module scores the tailored document instead. Two things make that honest
rather than a way to manufacture a number:

* **Evidence terms come from the original resume, never from the tailored
  text.** ``sanitize_match_payload`` drops any skill the model claims as a match
  unless the candidate's real documents evidence it, and re-derives the score
  from what survives. Building the evidence set from the tailored bullets would
  defeat exactly that check - the model could write "Kubernetes" into a bullet
  and then match against its own output. The evidence set is therefore built
  from the untouched profile, resume and accomplishments.

* **The text scored is the document that gets submitted.** The rendered PDF is
  the candidate's original resume with the Microsoft and Amazon bullet regions
  overlaid (see ``render_tailored_resume_pdf``); everything else - summary,
  Liquiron, Persistent Systems, education, featured projects - is untouched. So
  the scored text is the original resume with exactly that region swapped, not
  the bullets alone, which would score as if the rest of the resume vanished.

A score that rises here means the submitted document evidences more of the
posting than the stored one did, using only experience the candidate really
has. A score that does not rise is the honest answer, and the caller is
expected to treat it as one.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("career_os.tailored_match")

#: Where the experience section the overlay replaces begins and ends in the
#: resume text. The overlay covers the Microsoft and Amazon bullets only, so the
#: swap has to stop at the first role that is left alone.
_EXPERIENCE_START = re.compile(r"Senior Software Engineer\s*\|\s*Microsoft", re.I)
_EXPERIENCE_END = re.compile(r"Software Engineering Intern\s*\|\s*Liquiron", re.I)


def strip_markup(text: str) -> str:
    return re.sub(r"<[^>]+>", "", str(text or "")).strip()


def build_submitted_resume_text(original_text: str, tailored_bullets: list[str]) -> str:
    """The text of the PDF that will actually be sent.

    Falls back to appending rather than replacing when the section markers are
    not found: a resume whose headings changed should score against too much
    context rather than against the bullets alone, because the latter silently
    discards education, projects and two other roles and would read as a much
    weaker candidate than the document really is.
    """
    bullets = "\n".join(f"- {strip_markup(b)}" for b in tailored_bullets if strip_markup(b))
    base = str(original_text or "").strip()
    if not bullets:
        return base
    if not base:
        return bullets

    start = _EXPERIENCE_START.search(base)
    end = _EXPERIENCE_END.search(base)
    if not start or not end or end.start() <= start.start():
        logger.info(
            "Resume section markers not found; scoring tailored bullets alongside "
            "the full original resume instead of replacing the experience section."
        )
        return f"{base}\n\nTailored experience bullets for this application:\n{bullets}"

    head = base[: start.start()].rstrip()
    tail = base[end.start() :].lstrip()
    return f"{head}\n\nEXPERIENCE (as submitted for this role)\n{bullets}\n\n{tail}"


async def score_tailored_resume(
    job: dict[str, Any],
    tailored_bullets: list[str],
    *,
    profile: dict[str, Any],
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
    timeout: int | None = None,
) -> dict[str, Any] | None:
    """Score the tailored document. Returns None when the model is unusable.

    None means "could not score", never "scored zero" - the caller must not read
    a model outage as a failed match and reject a resume over it.
    """
    from app.services.application_assistant.candidate_match_context import (
        build_candidate_summary_for_llm,
        extract_resume_text,
    )
    from app.services.application_assistant.mistral_resume_match import (
        build_candidate_evidence,
        build_mistral_match_client,
        score_job_against_resume,
    )

    cleaned = [b for b in (tailored_bullets or []) if strip_markup(b)]
    if not cleaned:
        return None

    # Evidence stays anchored to the untouched documents - this is the anti-
    # fabrication anchor described in the module docstring.
    _, evidence_text, evidence_terms = build_candidate_evidence(
        profile, documents=documents, accomplishments=accomplishments
    )

    submitted_text = build_submitted_resume_text(extract_resume_text(documents), cleaned)

    # Score through the same builder the queue scorer uses, with only the resume
    # swapped. The number this produces is compared against the 80% submit bar,
    # and that bar was calibrated on queue scores built from profile + resume +
    # accomplishments. Scoring the resume text alone measures a different thing
    # on a different scale: it drops the profile skills and the accomplishment
    # corpus entirely, so a tailored resume came back *below* the untailored
    # score it was supposed to beat, and the retry loop read that as tailoring
    # having made things worse. Same inputs, one substitution, comparable
    # numbers.
    summary = build_candidate_summary_for_llm(
        profile,
        documents={"defaultResume": {"parsedText": submitted_text}},
        accomplishments=accomplishments,
    )

    client = build_mistral_match_client(timeout=timeout)
    if not client.enabled:
        logger.info("Local match model disabled; cannot score the tailored resume.")
        return None

    try:
        return await score_job_against_resume(
            client,
            job,
            candidate_summary=summary,
            evidence_text=evidence_text,
            evidence_terms=evidence_terms,
        )
    except Exception as exc:  # noqa: BLE001 - scoring must not break a submission
        logger.warning("Tailored-resume scoring failed for %s: %s", job.get("id"), exc)
        return None


def describe_gaps(score_payload: dict[str, Any] | None, limit: int = 8) -> list[str]:
    """The requirements the scorer said the tailored resume still does not show.

    This is what the next tailoring attempt is told to close, which is the only
    thing that makes a retry different from a re-roll of the same prompt.
    """
    if not isinstance(score_payload, dict):
        return []
    missing = score_payload.get("missingSkills")
    if not isinstance(missing, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in missing:
        text = str(item or "").strip()
        key = text.lower()
        if text and key not in seen:
            out.append(text)
            seen.add(key)
        if len(out) >= limit:
            break
    return out
