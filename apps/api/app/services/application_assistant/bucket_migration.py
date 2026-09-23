"""One-time move of existing Autopilot jobs onto the 2026-09-23 bucket model.

The repo owner redefined the buckets: FAILED is a dead end that is never
retried, anything retryable lives in NEEDS_REVIEW / MANUAL_REVIEW, and
INELIGIBLE means only that the candidate is barred from the role. New outcomes
follow that through ``submission_outcome`` and ``ineligibility``; this brings
the rows written under the old model into line, once.

It also re-checks jobs rejected as "outside the United States". Those labels
were written between 2026-09-12 and 09-15 by an older location check that, for
example, read "US-WA-Bellevue" as foreign; nothing ever re-evaluated them after
the check was fixed. Each is run through today's hard filters and returned to
the queue if it passes.

Idempotent: the version is recorded in KV and the pass runs at most once.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from app.db.store import get_kv, list_entities, now_iso, set_kv, upsert_entity

logger = logging.getLogger("career_os.application_assistant.bucket_migration")

BUCKET_MODEL_VERSION = 2
KV_BUCKET_MODEL = "autopilot_bucket_model"


def migrate_bucket_model(db: Any) -> dict[str, Any]:
    """Reclassify existing jobs onto the current bucket model. Safe to call on every start."""
    from app.services.application_assistant.ineligibility import FAILED_REASONS
    from app.services.application_assistant.job_filter_ranker import evaluate_hard_filters
    from app.services.application_assistant.persistence import (
        ENTITY_AUTOPILOT_JOB,
        _invalidate_autopilot_jobs_cache,
    )
    from app.services.application_assistant.submission_outcome import submit_was_attempted

    state = get_kv(db, KV_BUCKET_MODEL) or {}
    if state.get("version") == BUCKET_MODEL_VERSION:
        return {"skipped": True, **state}

    failed_reasons = {reason.value for reason in FAILED_REASONS}
    profile = get_kv(db, "profile") or {}
    counts: Counter[str] = Counter()

    for job in list_entities(db, ENTITY_AUTOPILOT_JOB):
        status = job.get("status")
        reason = job.get("ineligibilityReason")
        previous = status

        if status == "FAILED":
            if reason in failed_reasons:
                continue  # already a dead end in the new sense
            if submit_was_attempted(job):
                # The click may have reached the employer: never make it retryable.
                counts["failed_kept_submit_attempted"] += 1
                continue
            job["status"] = "NEEDS_REVIEW"
            job["technicalFailure"] = True
            counts["failed_to_needs_review"] += 1
        elif status == "INELIGIBLE" and reason in failed_reasons:
            job["status"] = "FAILED"
            job["hasPersistentBlock"] = True
            counts["ineligible_to_failed"] += 1
        elif status == "INELIGIBLE" and reason == "OUTSIDE_UNITED_STATES":
            passes, why = evaluate_hard_filters(job, profile, [])
            if not passes:
                counts["outside_us_still_rejected"] += 1
                continue
            # Duplicate protection is not bypassed: the runner re-checks every
            # job against earlier submissions before any attempt.
            job["status"] = "QUEUED"
            job["queuedAt"] = now_iso()
            job["hasPersistentBlock"] = False
            job.pop("ineligibilityReason", None)
            job.pop("ineligibilityDetail", None)
            job["lastError"] = None
            counts["outside_us_requeued"] += 1
        else:
            continue

        job["previousStatus"] = previous
        job["bucketModelMigratedFrom"] = previous
        job["updatedAt"] = now_iso()
        upsert_entity(db, ENTITY_AUTOPILOT_JOB, job)

    result = {"version": BUCKET_MODEL_VERSION, "migratedAt": now_iso(), "counts": dict(counts)}
    set_kv(db, KV_BUCKET_MODEL, result)
    _invalidate_autopilot_jobs_cache()
    logger.info("Autopilot bucket model v%s applied: %s", BUCKET_MODEL_VERSION, dict(counts))
    return result
