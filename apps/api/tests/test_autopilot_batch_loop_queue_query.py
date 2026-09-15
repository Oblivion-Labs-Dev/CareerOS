"""Regression test for a real production incident (2026-09-15, see NIGHT_BATCH_DECISIONS.md):
the batch loop's `_process_batch_loop` called `list_autopilot_jobs(db)` (a full, unfiltered
scan of every `aa_autopilot_job` row) on every single loop iteration — i.e. after every job —
just to filter down to the QUEUED ones in Python. Confirmed live via py-spy: the MainThread
itself sat blocked in this exact call, freezing the *entire server* (not even `/health`
responded) on every iteration, worsening as the job table grew (2500+ rows).

`list_autopilot_jobs` already supports pushing a status filter into SQLite via
`list_entities_by_json_equals` (an indexed `json_extract` query, see its own docstring) — the
fix was simply to pass `status=` at each of the four call sites instead of fetching everything
and filtering after the fact. This test proves the status-filtered call returns exactly the
same set as the old fetch-everything-then-filter-in-Python approach.
"""

from __future__ import annotations

from app.db.store import session_scope, upsert_entity
from app.services.application_assistant.persistence import ENTITY_AUTOPILOT_JOB, list_autopilot_jobs


def test_status_filtered_query_matches_manual_python_filter() -> None:
    with session_scope() as db:
        seeded_ids = []
        for i, status in enumerate(["QUEUED", "QUEUED", "SUBMITTED", "FAILED", "QUEUED", "MANUAL_REVIEW"]):
            job = upsert_entity(
                db,
                ENTITY_AUTOPILOT_JOB,
                {"company": f"TestCo{i}", "title": "Engineer", "status": status, "applicationUrl": f"https://example.com/{i}"},
            )
            seeded_ids.append(job["id"])

        all_jobs = list_autopilot_jobs(db)
        expected_queued_ids = {
            j["id"] for j in all_jobs if j.get("status") == "QUEUED" and j["id"] in seeded_ids
        }

        queued_via_filter = list_autopilot_jobs(db, status="QUEUED")
        actual_queued_ids = {j["id"] for j in queued_via_filter if j["id"] in seeded_ids}

        assert actual_queued_ids == expected_queued_ids
        assert len(expected_queued_ids) == 3
