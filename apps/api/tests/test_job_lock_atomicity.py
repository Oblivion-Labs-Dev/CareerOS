"""The job lease must admit exactly one worker, even under contention."""

from __future__ import annotations

import concurrent.futures

from app.db.store import session_scope
from app.services.application_assistant.persistence import (
    claim_job_lock,
    get_autopilot_job,
    release_job_lock,
    save_autopilot_job,
)


def _make_job(job_id: str) -> None:
    with session_scope() as db:
        save_autopilot_job(db, {"id": job_id, "status": "QUEUED", "company": "LockTest"})


def _cleanup(job_id: str) -> None:
    from app.services.application_assistant.persistence import delete_autopilot_job

    with session_scope() as db:
        delete_autopilot_job(db, job_id)


def test_single_worker_wins_an_uncontended_lock():
    job_id = "apjob_lock_basic"
    _make_job(job_id)
    try:
        with session_scope() as db:
            assert claim_job_lock(db, job_id, "worker-a") is True
        with session_scope() as db:
            job = get_autopilot_job(db, job_id)
        assert job["lockedBy"] == "worker-a"
        assert job["lockExpiresAt"] > job["lockedAt"]
    finally:
        _cleanup(job_id)


def test_second_worker_is_refused_while_lease_is_live():
    job_id = "apjob_lock_contended"
    _make_job(job_id)
    try:
        with session_scope() as db:
            assert claim_job_lock(db, job_id, "worker-a") is True
        with session_scope() as db:
            assert claim_job_lock(db, job_id, "worker-b") is False
        with session_scope() as db:
            assert get_autopilot_job(db, job_id)["lockedBy"] == "worker-a"
    finally:
        _cleanup(job_id)


def test_holder_may_extend_its_own_lease():
    job_id = "apjob_lock_reentrant"
    _make_job(job_id)
    try:
        with session_scope() as db:
            assert claim_job_lock(db, job_id, "worker-a") is True
        with session_scope() as db:
            assert claim_job_lock(db, job_id, "worker-a") is True
    finally:
        _cleanup(job_id)


def test_expired_lease_is_reclaimable():
    job_id = "apjob_lock_expired"
    _make_job(job_id)
    try:
        with session_scope() as db:
            claim_job_lock(db, job_id, "worker-a", lease_seconds=-5)
        with session_scope() as db:
            assert claim_job_lock(db, job_id, "worker-b") is True
            assert get_autopilot_job(db, job_id)["lockedBy"] == "worker-b"
    finally:
        _cleanup(job_id)


def test_released_lock_is_reclaimable():
    job_id = "apjob_lock_released"
    _make_job(job_id)
    try:
        with session_scope() as db:
            claim_job_lock(db, job_id, "worker-a")
        with session_scope() as db:
            release_job_lock(db, job_id, "worker-a")
        with session_scope() as db:
            assert claim_job_lock(db, job_id, "worker-b") is True
    finally:
        _cleanup(job_id)


def test_concurrent_claims_admit_exactly_one_worker():
    """The regression this exists for.

    Eight threads race for one job. With the old read-check-write claim, more
    than one could observe the job unlocked and all of them would proceed to
    submit. Exactly one must win.
    """
    job_id = "apjob_lock_race"
    _make_job(job_id)
    try:
        def attempt(worker: int) -> bool:
            with session_scope() as db:
                return claim_job_lock(db, job_id, f"worker-{worker}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))

        assert sum(1 for won in results if won) == 1, (
            f"expected exactly one winner, got {sum(1 for w in results if w)}"
        )
    finally:
        _cleanup(job_id)
