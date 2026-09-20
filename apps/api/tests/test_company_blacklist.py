"""The candidate's own do-not-apply list.

Unlike `company_cap`'s pacing hold (temporary, keeps the job QUEUED), a
blacklist entry is the candidate's standing decision — a blacklisted job is
filed INELIGIBLE, a genuine dead end, until the candidate removes the company
from Settings.
"""

from __future__ import annotations

from app.services.application_assistant.company_blacklist import (
    is_blacklisted,
    partition_by_blacklist,
)
from app.services.application_assistant.domain import AutopilotJobStatus, IneligibilityReason


def _job(job_id: str, company: str) -> dict:
    return {"id": job_id, "company": company, "status": "QUEUED"}


def test_empty_blacklist_blocks_nothing():
    queued = [_job("a", "Acme")]

    allowed, blocked = partition_by_blacklist(queued, [])

    assert allowed == queued
    assert blocked == []


def test_a_blacklisted_company_is_filed_ineligible():
    queued = [_job("a", "Acme")]
    blacklist = [{"company": "Acme", "reason": "Ghosted me after onsite"}]

    allowed, blocked = partition_by_blacklist(queued, blacklist)

    assert allowed == []
    assert len(blocked) == 1
    job = blocked[0]
    assert job["status"] == AutopilotJobStatus.INELIGIBLE.value
    assert job["ineligibilityReason"] == IneligibilityReason.COMPANY_BLACKLISTED.value
    assert "Ghosted me after onsite" in job["ineligibilityDetail"]


def test_company_names_match_loosely_like_company_cap():
    """Boards spell one employer several ways; a blacklist fooled by that
    lets exactly the postings the candidate meant to block straight through."""
    queued = [_job("a", "DoorDash USA"), _job("b", "doordashusa"), _job("c", "Door-Dash  USA")]
    blacklist = [{"company": "DoorDash", "reason": "test"}]

    allowed, blocked = partition_by_blacklist(queued, blacklist)

    assert allowed == queued
    assert blocked == []

    blacklist_exact = [{"company": "DoorDash USA", "reason": "test"}]
    allowed2, blocked2 = partition_by_blacklist(queued, blacklist_exact)
    assert allowed2 == []
    assert len(blocked2) == 3


def test_one_blacklisted_company_does_not_block_others():
    queued = [_job("a", "Acme"), _job("b", "Globex")]
    blacklist = [{"company": "Acme", "reason": "test"}]

    allowed, blocked = partition_by_blacklist(queued, blacklist)

    assert [j["id"] for j in allowed] == ["b"]
    assert [j["id"] for j in blocked] == ["a"]


def test_a_reasonless_entry_still_blocks_with_a_generic_message():
    queued = [_job("a", "Acme")]
    blacklist = [{"company": "Acme"}]

    _, blocked = partition_by_blacklist(queued, blacklist)

    assert blocked[0]["ineligibilityDetail"] == "Acme is on your do-not-apply list."


def test_a_job_with_no_company_is_never_matched():
    queued = [{"id": "a", "company": "", "status": "QUEUED"}]
    blacklist = [{"company": "", "reason": "should never match"}]

    allowed, blocked = partition_by_blacklist(queued, blacklist)

    assert allowed == queued
    assert blocked == []


def test_is_blacklisted_returns_the_reason_or_none():
    blacklist = [{"company": "Acme", "reason": "Bad interview experience"}]

    assert is_blacklisted("ACME", blacklist) == "Bad interview experience"
    assert is_blacklisted("Globex", blacklist) is None
