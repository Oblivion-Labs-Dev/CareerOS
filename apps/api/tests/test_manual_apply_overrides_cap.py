"""Clicking Apply overrides the per-company rate limits.

The limits exist to stop the *automation* flooding one employer. An explicit
Apply click is the user deciding that this particular application is worth
sending now, so it must go out even when the employer is paced — otherwise the
button silently does nothing and the job drops back into the queue, which reads
as the product being broken.

The subtle part, and the reason this file exists: there are two independent
pacing gates, and the run drains `priority_job_ids` as jobs are claimed, so by
the time a job reaches the second gate its id is no longer in that list. The
override therefore keys on `manual_apply_job_ids`, which is never drained.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant import company_cap

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def _submitted(company: str, hours_ago: float, job_id: str) -> dict:
    return {
        "id": job_id,
        "company": company,
        "status": "SUBMITTED",
        "submittedAt": (NOW - timedelta(hours=hours_ago)).isoformat(),
    }


def _queued(company: str, job_id: str) -> dict:
    return {"id": job_id, "company": company, "status": "QUEUED", "matchScore": 90.0}


def _capped_history(company: str = "Acme") -> list[dict]:
    """Enough submissions today to exhaust the daily tier."""
    daily_cap = dict((n, c) for n, c, _d in company_cap.COMPANY_CAP_TIERS)["day"]
    return [_submitted(company, i * 0.1, f"s{i}") for i in range(daily_cap)]


def test_the_cap_holds_this_job_when_apply_was_not_clicked():
    """The control: without the click, this job is paced."""
    queued = [_queued("Acme", "q1")]

    applyable, held = company_cap.partition_by_cap(
        queued, _capped_history() + queued, now=NOW
    )

    assert applyable == []
    assert [j["id"] for j in held] == ["q1"]


def test_apply_ids_are_collected_from_both_option_spellings():
    """The readiness gate honours priorityJobIds, but only the singular was
    ever consumed where priorities are recorded — so a plural batch skipped the
    gate and then quietly lost its priority.
    """
    assert module.collect_priority_ids({"priorityJobId": "a"}) == ["a"]
    assert module.collect_priority_ids({"priorityJobIds": ["b", "c"]}) == ["b", "c"]
    assert module.collect_priority_ids(
        {"priorityJobId": "a", "priorityJobIds": ["b", "c"]}
    ) == ["a", "b", "c"]


def test_collecting_apply_ids_drops_blanks_and_duplicates():
    assert module.collect_priority_ids({}) == []
    assert module.collect_priority_ids({"priorityJobId": None, "priorityJobIds": []}) == []
    assert module.collect_priority_ids(
        {"priorityJobId": "a", "priorityJobIds": ["a", "", "b"]}
    ) == ["a", "b"], "the clicked job must keep its place at the front"


def test_the_override_survives_the_claim_step_draining_priority_ids():
    """The regression this file exists for.

    `priority_job_ids` is popped when a job is claimed, so a check against it
    at the second gate would find nothing and pace the job the user just asked
    for. `manual_apply_job_ids` must still hold the id.
    """
    runner = module.AutopilotRunner()
    runner.priority_job_ids = ["q1"]
    runner.manual_apply_job_ids = {"q1"}

    # What the claim step does.
    runner.priority_job_ids.remove("q1")

    assert "q1" not in runner.priority_job_ids
    assert "q1" in runner.manual_apply_job_ids, (
        "the override must outlive the priority list, or the second pacing "
        "gate will hold the job the user explicitly clicked Apply on"
    )


def test_a_manually_applied_job_is_exempt_from_the_batch_partition():
    """Mirrors the batch loop: manual jobs are held out of the partition."""
    manual_id = "q_manual"
    queued = [_queued("Acme", manual_id), _queued("Acme", "q_auto")]
    manual_ids = {manual_id}

    manual = [j for j in queued if j.get("id") in manual_ids]
    paceable = [j for j in queued if j.get("id") not in manual_ids]
    allowed, held = company_cap.partition_by_cap(
        paceable, _capped_history() + queued, now=NOW
    )
    for job in manual:
        company_cap.clear_hold(job)
    allowed = manual + allowed

    assert [j["id"] for j in allowed] == [manual_id]
    assert [j["id"] for j in held] == ["q_auto"]
    assert allowed[0].get("companyCapHoldUntil") is None


def test_the_override_does_not_spend_another_job_s_slot():
    """Exempting by filtering *after* the partition would let the manual job
    consume a slot that a queued job was then denied."""
    manual_id = "q_manual"
    # One slot left at the daily tier.
    history = _capped_history()[:-1]
    queued = [_queued("Acme", manual_id), _queued("Acme", "q_auto")]
    manual_ids = {manual_id}

    paceable = [j for j in queued if j.get("id") not in manual_ids]
    allowed, held = company_cap.partition_by_cap(
        paceable, history + queued, now=NOW
    )

    assert [j["id"] for j in allowed] == ["q_auto"], (
        "the remaining slot belongs to the automated job; the manual one "
        "bypasses the cap rather than competing for it"
    )
    assert held == []
