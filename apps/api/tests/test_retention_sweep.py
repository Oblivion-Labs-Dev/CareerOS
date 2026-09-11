"""Retention must delete only what is genuinely stale and unreachable."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.store import EntityStore, session_scope, upsert_entity
from app.services import retention


def _iso(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


@pytest.fixture(autouse=True)
def clean_tables():
    types = ("aa_discovered_job", "aa_form_field", "aa_autopilot_run", "model_usage_event", "aa_autopilot_job")
    with session_scope() as db:
        for t in types:
            db.query(EntityStore).filter(EntityStore.entity_type == t).delete(synchronize_session=False)
    yield
    with session_scope() as db:
        for t in types:
            db.query(EntityStore).filter(EntityStore.entity_type == t).delete(synchronize_session=False)


def _put(entity_type: str, payload: dict) -> None:
    with session_scope() as db:
        upsert_entity(db, entity_type, payload)


def test_old_unreferenced_discovered_job_is_removed():
    _put("aa_discovered_job", {"id": "d-old", "lastSeenDate": _iso(400)})
    report = retention.sweep(dry_run=False)
    assert report.removed["aa_discovered_job"] == 1


def test_recent_discovered_job_is_kept():
    _put("aa_discovered_job", {"id": "d-new", "lastSeenDate": _iso(2)})
    report = retention.sweep(dry_run=False)
    assert report.removed["aa_discovered_job"] == 0


def test_row_without_any_timestamp_is_kept():
    """The regression this file exists for.

    An earlier draft used coalesce(ts, '') < cutoff. An empty string sorts
    before every date, so every row missing a timestamp matched as ancient -
    it selected 7,044 of 7,076 real discovered jobs for deletion.
    """
    _put("aa_discovered_job", {"id": "d-undated", "title": "No timestamps at all"})
    report = retention.sweep(dry_run=False)
    assert report.removed["aa_discovered_job"] == 0

    with session_scope() as db:
        assert db.query(EntityStore).filter(EntityStore.id == "d-undated").one_or_none() is not None


def test_old_job_added_to_assistant_is_kept():
    """Age alone never justifies deleting something the user imported."""
    _put("aa_discovered_job", {"id": "d-imported", "lastSeenDate": _iso(400), "addedToAssistant": True})
    report = retention.sweep(dry_run=False)
    assert report.removed["aa_discovered_job"] == 0


def test_dry_run_deletes_nothing_but_still_counts():
    _put("aa_discovered_job", {"id": "d-old-2", "lastSeenDate": _iso(400)})
    report = retention.sweep(dry_run=True)
    assert report.dry_run is True
    assert report.removed["aa_discovered_job"] == 1
    with session_scope() as db:
        assert db.query(EntityStore).filter(EntityStore.id == "d-old-2").one_or_none() is not None


def test_form_fields_kept_while_application_is_open():
    _put("aa_autopilot_job", {"id": "app-open", "status": "QUEUED"})
    _put("aa_form_field", {"id": "f-open", "applicationId": "app-open", "discoveredAt": _iso(400)})
    report = retention.sweep(dry_run=False)
    assert report.removed["aa_form_field"] == 0


def test_form_fields_removed_once_application_is_terminal():
    _put("aa_autopilot_job", {"id": "app-done", "status": "SUBMITTED"})
    _put("aa_form_field", {"id": "f-done", "applicationId": "app-done", "discoveredAt": _iso(400)})
    report = retention.sweep(dry_run=False)
    assert report.removed["aa_form_field"] == 1


def test_unfinished_run_is_kept():
    _put("aa_autopilot_run", {"id": "run-live", "startedAt": _iso(400)})
    report = retention.sweep(dry_run=False)
    assert report.removed["aa_autopilot_run"] == 0


def test_finished_old_run_is_removed():
    _put("aa_autopilot_run", {"id": "run-done", "completedAt": _iso(400)})
    report = retention.sweep(dry_run=False)
    assert report.removed["aa_autopilot_run"] == 1


def test_updated_at_cannot_keep_a_row_alive_forever():
    """upsert_entity stamps updatedAt on every write.

    Aging on that field meant any row re-saved for an unrelated reason reset its
    retention clock. Capture time is what decides.
    """
    _put("aa_autopilot_job", {"id": "app-t", "status": "SUBMITTED"})
    _put("aa_form_field", {"id": "f-touched", "applicationId": "app-t", "discoveredAt": _iso(400)})
    # Re-save it: updatedAt becomes now, discoveredAt does not move.
    _put("aa_form_field", {"id": "f-touched", "applicationId": "app-t", "discoveredAt": _iso(400)})
    assert retention.sweep(dry_run=False).removed["aa_form_field"] == 1


def test_sweep_is_idempotent():
    _put("aa_discovered_job", {"id": "d-x", "lastSeenDate": _iso(400)})
    assert retention.sweep(dry_run=False).removed["aa_discovered_job"] == 1
    assert retention.sweep(dry_run=False).removed["aa_discovered_job"] == 0
