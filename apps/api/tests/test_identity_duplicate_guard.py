"""#37: one ATS posting must never be submitted twice through two job records.

The in-flight claim is keyed on the ATS posting id, but it is released after
every attempt, and the post-submission guards matched only on canonical URL or
exact (company, title). Two records for one Greenhouse posting - the
boards.greenhouse.io URL and the employer's `?gh_jid=` mirror, with slightly
different titles - slipped past all of them.
"""

from __future__ import annotations

from app.db.store import session_scope
from app.services.application_assistant.ineligibility import find_duplicate_submission
from app.services.application_assistant.persistence import (
    delete_autopilot_job,
    get_autopilot_job,
    list_submitted_duplicate_candidates,
    save_autopilot_job,
)

BOARD_URL = "https://boards.greenhouse.io/acme/jobs/7788991"
MIRROR_URL = "https://careers.acme.com/openings/senior-backend?gh_jid=7788991"


def _record(job_id: str, url: str, title: str, company: str, status: str) -> dict:
    return {"id": job_id, "company": company, "title": title, "applicationUrl": url, "status": status}


def _save(job: dict) -> dict:
    with session_scope() as db:
        return save_autopilot_job(db, dict(job))


def _read(job_id: str) -> dict | None:
    with session_scope() as db:
        return get_autopilot_job(db, job_id)


def _drop(*job_ids: str) -> None:
    with session_scope() as db:
        for job_id in job_ids:
            delete_autopilot_job(db, job_id)


def _refused_by_precheck(job: dict) -> dict | None:
    """The runner's step-4 pre-check, exactly as it calls it."""
    with session_scope() as db:
        candidates = list_submitted_duplicate_candidates(db, job)
    return find_duplicate_submission(job, candidates)


def test_submitting_one_record_retires_its_same_posting_sibling():
    sibling = _save(_record("apjob_id37_b", MIRROR_URL, "Sr. Backend Engineer", "ACME Corp", "QUEUED"))
    try:
        _save(_record("apjob_id37_a", BOARD_URL, "Senior Backend Engineer", "Acme", "SUBMITTED"))
        retired = _read(sibling["id"])
        assert retired["status"] == "FAILED"
        assert retired["ineligibilityReason"] == "DUPLICATE_APPLICATION"
    finally:
        _drop("apjob_id37_a", "apjob_id37_b")


def test_precheck_refuses_a_same_posting_record_after_submission():
    # Saved in this order so close_duplicate_applications can't have retired
    # it: the pre-check itself must refuse it.
    _save(_record("apjob_id37_c", BOARD_URL, "Senior Backend Engineer", "Acme", "SUBMITTED"))
    try:
        other = _record("apjob_id37_d", MIRROR_URL, "Sr. Backend Engineer", "ACME Corp", "QUEUED")
        match = _refused_by_precheck(other)
        assert match is not None and match["id"] == "apjob_id37_c"
    finally:
        _drop("apjob_id37_c")


def test_a_maybe_submitted_record_with_no_email_yet_still_blocks_the_sibling():
    # Record A clicked submit but no confirmation email has arrived: it sits in
    # SUBMISSION_UNKNOWN. Gmail is never permission to retry, so B must still
    # be refused.
    _save(_record("apjob_id37_e", BOARD_URL, "Senior Backend Engineer", "Acme", "SUBMISSION_UNKNOWN"))
    try:
        other = _record("apjob_id37_f", MIRROR_URL, "Sr. Backend Engineer", "ACME Corp", "QUEUED")
        match = _refused_by_precheck(other)
        assert match is not None and match["id"] == "apjob_id37_e"
    finally:
        _drop("apjob_id37_e")


def test_different_postings_at_the_same_company_are_not_confused():
    _save(_record("apjob_id37_g", BOARD_URL, "Senior Backend Engineer", "Acme", "SUBMITTED"))
    try:
        other = _record(
            "apjob_id37_h", "https://boards.greenhouse.io/acme/jobs/7788992",
            "Senior Frontend Engineer", "Acme", "QUEUED",
        )
        assert _refused_by_precheck(other) is None
    finally:
        _drop("apjob_id37_g")


def test_saved_records_carry_their_application_identity():
    saved = _save(_record("apjob_id37_i", MIRROR_URL, "Sr. Backend Engineer", "Acme", "QUEUED"))
    try:
        assert saved["applicationIdentity"] == "gh:7788991"
    finally:
        _drop("apjob_id37_i")


def test_query_string_postings_on_one_page_are_not_confused():
    # The `url:` identity drops the query, so these two share it. They are two
    # different openings and must not refuse each other.
    _save(_record("apjob_id37_j", "https://jobs.example.com/job?id=111", "Senior Engineer", "Example", "SUBMITTED"))
    try:
        other = _record("apjob_id37_k", "https://jobs.example.com/job?id=222", "Staff Engineer", "Example", "QUEUED")
        assert _refused_by_precheck(other) is None
    finally:
        _drop("apjob_id37_j")
