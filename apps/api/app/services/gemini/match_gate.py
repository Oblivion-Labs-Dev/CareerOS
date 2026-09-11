"""Whether an ambiguous posting may proceed, or belongs in review.

This is the only place a Gemini result is allowed to influence an application,
and it is deliberately shaped so that it can only ever be *more* cautious than
the deterministic path, never less.

Three rules define it:

* **A confident deterministic result is never sent to Gemini.** `ambiguity.assess`
  runs first, costs microseconds, and most postings stop there. Gemini is not in
  the normal matching path and adds no latency to it.
* **Gemini can send a posting to review; it cannot send one to apply.** A posting
  the deterministic matcher was going to apply to and that Gemini reads as a
  mismatch goes to review for the user to judge. A posting Gemini likes is
  simply allowed to continue on the deterministic decision it already had. So
  the worst case of a wrong Gemini answer is a posting the user looks at by
  hand, which is the workflow they already run.
* **Gemini being unavailable produces review, never failure.** An ambiguous
  posting with no second opinion is exactly what the review bucket is for. It
  does not fail the run, it does not get skipped, and it does not get applied to
  on a coin flip.

The deterministic assessment and the Gemini judgement are both returned, and the
caller stores both. Keeping them apart is what will make it possible to measure
whether Gemini is actually improving decisions rather than just being consulted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.gemini import ambiguity, enrichment
from app.services.gemini.grounding import Corpus
from app.services.gemini.telemetry import telemetry

logger = logging.getLogger("careeros.gemini.match_gate")

PROCEED = "PROCEED"
REVIEW = "REVIEW"

#: How sure Gemini must be before its opinion is allowed to divert a posting to
#: review. Below this it is not disagreeing, it is guessing, and a guess should
#: not override a deterministic score.
MIN_DIVERT_CONFIDENCE = 0.6


@dataclass
class GateDecision:
    action: str
    reason: str
    consulted: bool = False
    uncertainty: dict[str, Any] = field(default_factory=dict)
    gemini: dict[str, Any] | None = None

    @property
    def proceed(self) -> bool:
        return self.action == PROCEED

    def to_job_fields(self) -> dict[str, Any]:
        """What to persist on the job row. Never touches `matchScore`.

        The deterministic score stays exactly as the matcher produced it. The
        Gemini view is stored beside it under its own key so the two can be
        compared later instead of one having quietly replaced the other.
        """
        payload: dict[str, Any] = {"geminiMatchGate": {
            "action": self.action,
            "reason": self.reason,
            "consulted": self.consulted,
            "uncertainty": self.uncertainty,
        }}
        if self.gemini is not None:
            payload["geminiMatchGate"]["gemini"] = self.gemini
        return payload


async def evaluate(
    job: dict[str, Any],
    *,
    score: float | None = None,
    profile: dict[str, Any] | None = None,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
    corpus: Corpus | None = None,
) -> GateDecision:
    """Decide whether this posting continues, or goes to review. Never raises."""
    try:
        uncertainty = ambiguity.assess(job, score=score)
    except Exception:  # noqa: BLE001 - a gate must not be able to fail a run
        logger.exception("Ambiguity assessment failed; proceeding deterministically")
        return GateDecision(action=PROCEED, reason="ambiguity assessment failed; deterministic result stands")

    if not uncertainty.ambiguous:
        # The overwhelmingly common path: no call, no queue, no latency.
        return GateDecision(
            action=PROCEED,
            reason="deterministic match was confident",
            uncertainty=uncertainty.to_dict(),
        )

    try:
        result = await enrichment.clarify_match(
            job, uncertainty,
            corpus=corpus, profile=profile,
            documents=documents, accomplishments=accomplishments,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Gemini match clarification raised; staging for review")
        result = enrichment.MatchEnrichment(available=False, outcome="error", reason=str(exc)[:200])

    if not result.available:
        telemetry.record_review_staging()
        return GateDecision(
            action=REVIEW,
            consulted=True,
            reason=(
                "Match was ambiguous and no second opinion was available "
                f"({result.outcome or 'unavailable'}): "
                + "; ".join(uncertainty.reasons)
            )[:400],
            uncertainty=uncertainty.to_dict(),
        )

    view = result.to_dict()

    if result.confidence < MIN_DIVERT_CONFIDENCE:
        return GateDecision(
            action=PROCEED,
            consulted=True,
            reason=(
                f"Second opinion was too unsure to act on ({result.confidence:.2f}); "
                "deterministic result stands"
            ),
            uncertainty=uncertainty.to_dict(),
            gemini=view,
        )

    if result.decision == "SKIP" or result.critical_mismatch:
        detail = result.reason or "assessed as a mismatch"
        if result.critical_requirements:
            detail += " (unmet: " + ", ".join(result.critical_requirements[:4]) + ")"
        return GateDecision(
            action=REVIEW,
            consulted=True,
            reason=f"Second opinion disagreed with the deterministic match: {detail}"[:400],
            uncertainty=uncertainty.to_dict(),
            gemini=view,
        )

    if result.decision == "REVIEW":
        return GateDecision(
            action=REVIEW,
            consulted=True,
            reason=f"Second opinion was also undecided: {result.reason}"[:400],
            uncertainty=uncertainty.to_dict(),
            gemini=view,
        )

    return GateDecision(
        action=PROCEED,
        consulted=True,
        reason=f"Second opinion agreed the posting is a fit: {result.reason}"[:400],
        uncertainty=uncertainty.to_dict(),
        gemini=view,
    )
