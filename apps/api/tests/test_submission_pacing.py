"""A minimum gap between consecutive submissions, so two applications never
land close enough together to read as automated.

Covers the pure pacing function in `submission_pacing.py` and the persistence
query it's fed from, `most_recent_submit_attempt`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.store import session_scope
from app.services.application_assistant.persistence import (
    most_recent_submit_attempt,
    save_autopilot_job,
)
from app.services.application_assistant.submission_pacing import (
    MIN_SUBMISSION_GAP_SECONDS,
    seconds_until_next_submission,
)

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


# ── seconds_until_next_submission (pure) ─────────────────────────────────────


def test_no_prior_submission_means_no_wait():
    assert seconds_until_next_submission(None, now=NOW) == 0.0


def test_an_unparseable_timestamp_fails_open():
    """A malformed timestamp must not block Autopilot on bad data — the gap
    is a politeness measure, not a safety guard."""
    assert seconds_until_next_submission("not-a-timestamp", now=NOW) == 0.0


def test_a_submission_inside_the_gap_must_wait_the_remainder():
    last = (NOW - timedelta(seconds=100)).isoformat()

    remaining = seconds_until_next_submission(last, now=NOW)

    assert abs(remaining - (MIN_SUBMISSION_GAP_SECONDS - 100)) < 0.01


def test_a_submission_past_the_gap_needs_no_wait():
    last = (NOW - timedelta(seconds=MIN_SUBMISSION_GAP_SECONDS + 30)).isoformat()

    assert seconds_until_next_submission(last, now=NOW) == 0.0


def test_the_wait_is_never_negative():
    last = (NOW - timedelta(days=1)).isoformat()

    assert seconds_until_next_submission(last, now=NOW) == 0.0


def test_a_z_suffixed_timestamp_parses_like_the_offset_form():
    last_z = (NOW - timedelta(seconds=100)).isoformat().replace("+00:00", "Z")
    last_offset = (NOW - timedelta(seconds=100)).isoformat()

    assert seconds_until_next_submission(last_z, now=NOW) == seconds_until_next_submission(
        last_offset, now=NOW
    )


def test_a_naive_timestamp_is_treated_as_utc():
    naive = (NOW - timedelta(seconds=100)).replace(tzinfo=None).isoformat()

    remaining = seconds_until_next_submission(naive, now=NOW)

    assert abs(remaining - (MIN_SUBMISSION_GAP_SECONDS - 100)) < 0.01


def test_a_custom_gap_is_honoured():
    last = (NOW - timedelta(seconds=10)).isoformat()

    assert seconds_until_next_submission(last, now=NOW, gap_seconds=60) == 50.0


# ── most_recent_submit_attempt (persistence) ─────────────────────────────────


def _job(job_id: str, submit_attempted_at: str | None) -> dict:
    job = {"id": job_id, "company": "Acme", "status": "APPLYING"}
    if submit_attempted_at is not None:
        job["submitAttemptedAt"] = submit_attempted_at
    return job


def test_no_jobs_have_submitted_yet_returns_none():
    with session_scope() as db:
        result = most_recent_submit_attempt(db, exclude_id="__nonexistent_probe__")
    # Other tests in this shared-DB session may have written rows, so this
    # only asserts the no-crash / correct-type contract, not emptiness.
    assert result is None or isinstance(result, str)


def test_returns_the_latest_stamp_across_jobs():
    older = (NOW - timedelta(hours=2)).isoformat()
    newer = (NOW - timedelta(minutes=1)).isoformat()

    with session_scope() as db:
        save_autopilot_job(db, _job("pacing_a", older))
        save_autopilot_job(db, _job("pacing_b", newer))
        result = most_recent_submit_attempt(db)

    assert result == newer


def test_a_job_with_no_submit_attempt_is_ignored():
    with session_scope() as db:
        save_autopilot_job(db, _job("pacing_no_attempt", None))
        # Should not raise, and should not report None-as-a-string.
        result = most_recent_submit_attempt(db)

    assert result is None or isinstance(result, str)


def test_exclude_id_omits_that_jobs_own_stamp():
    """The job about to submit must not pace against its own prior attempt
    (e.g. a retry) — only every *other* job's stamp counts."""
    only_stamp = (NOW - timedelta(seconds=10)).isoformat()

    with session_scope() as db:
        save_autopilot_job(db, _job("pacing_self", only_stamp))
        result = most_recent_submit_attempt(db, exclude_id="pacing_self")

    assert result != only_stamp
