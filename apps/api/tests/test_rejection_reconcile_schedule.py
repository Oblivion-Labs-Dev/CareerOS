"""Rejection reconciliation runs on a fixed daily schedule (configurable via
REJECTION_RECONCILE_HOURS_UTC), not the queue preprocessor's cycle-based
cadence — a full mailbox rejection-phrase scan is heavier than the
confirmation check and does not need same-minute detection.
"""

from datetime import datetime, timezone

from app.services.application_assistant.queue_preprocessor import (
    _due_for_scheduled_rejection_reconcile,
    _parse_reconcile_hours,
)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 17, hour, minute, tzinfo=timezone.utc)


class TestParseReconcileHours:
    def test_parses_comma_separated_hours(self):
        assert _parse_reconcile_hours("8,20") == [8, 20]

    def test_dedupes_and_sorts(self):
        assert _parse_reconcile_hours("20,8,8") == [8, 20]

    def test_ignores_out_of_range_and_malformed_entries(self):
        assert _parse_reconcile_hours("8,25,-1,abc,20") == [8, 20]

    def test_falls_back_to_default_when_nothing_valid(self):
        assert _parse_reconcile_hours("") == [8, 20]
        assert _parse_reconcile_hours("abc") == [8, 20]


class TestDueForScheduledReconcile:
    def test_never_run_before_and_past_first_scheduled_hour_is_due(self):
        assert _due_for_scheduled_rejection_reconcile(None, _at(8, 5)) is True

    def test_not_yet_due_before_the_first_scheduled_hour(self):
        assert _due_for_scheduled_rejection_reconcile(None, _at(7, 59)) is False

    def test_not_due_again_right_after_running_in_the_same_slot(self):
        last_run = _at(8, 0).isoformat()
        assert _due_for_scheduled_rejection_reconcile(last_run, _at(8, 30)) is False
        assert _due_for_scheduled_rejection_reconcile(last_run, _at(19, 59)) is False

    def test_due_again_once_the_evening_slot_arrives(self):
        last_run = _at(8, 0).isoformat()
        assert _due_for_scheduled_rejection_reconcile(last_run, _at(20, 0)) is True

    def test_due_again_the_next_morning_after_the_evening_run(self):
        last_run = _at(20, 0).isoformat()
        next_day_morning = datetime(2026, 9, 18, 8, 5, tzinfo=timezone.utc)
        assert _due_for_scheduled_rejection_reconcile(last_run, next_day_morning) is True

    def test_survives_a_restart_via_persisted_last_run_not_in_memory_state(self):
        # A run that already happened today at 8:00 must not re-fire just
        # because the process restarted and in-memory state was lost — the
        # persisted last-run timestamp is what this function is given.
        last_run = _at(8, 0).isoformat()
        assert _due_for_scheduled_rejection_reconcile(last_run, _at(8, 1)) is False

    def test_malformed_last_run_value_is_treated_as_never_run(self):
        assert _due_for_scheduled_rejection_reconcile("not-a-date", _at(8, 5)) is True
