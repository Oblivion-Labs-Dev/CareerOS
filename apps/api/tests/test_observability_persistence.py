"""DiagnosticErrorStore survives a restart.

Phase 3's logging audit found every in-memory store in observability.py —
despite `OpenTelemetryTracer`'s own docstring claiming "In-memory +
persisted" — had zero database writes anywhere in the file. Confirmed live:
`/diagnostic/errors` returned `{"total": 0}` on a dev server that had been
running for hours, because every restart silently wiped it. This is the
regression test for the fix: a fresh store (a new instance is exactly what a
process restart produces — the module-level `error_store` singleton starts
over with `self.errors = []`) must be able to load back what an earlier
instance recorded, not just count on itself never restarting.
"""

from __future__ import annotations

from app.db.store import session_scope
from app.services.observability import DiagnosticErrorStore


def test_a_recorded_error_survives_a_fresh_store_instance():
    original = DiagnosticErrorStore(max_errors=500)

    entry = original.record_error(
        error="Submit button not found",
        service="autopilot",
        severity="error",
        stage="APPLY",
    )

    # A fresh instance is exactly what happens on restart: the module-level
    # singleton is re-created empty. If persistence isn't real, this finds
    # nothing.
    restarted = DiagnosticErrorStore(max_errors=500)
    assert restarted.errors == []

    loaded_count = restarted.load_from_db()

    assert loaded_count >= 1
    restored = next((e for e in restarted.errors if e.id == entry.id), None)
    assert restored is not None, "the recorded error must survive into the new instance"
    assert restored.error == "Submit button not found"
    assert restored.severity == "error"
    assert restored.stage == "APPLY"

    # And it must actually answer queries, not just sit in the list.
    results = restarted.query(service="autopilot", limit=10)
    assert any(r["id"] == entry.id for r in results)


def test_load_from_db_never_raises_even_if_the_database_is_unreachable(monkeypatch):
    store = DiagnosticErrorStore(max_errors=500)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr("app.db.store.session_scope", _boom)

    # Must not raise — a failure here must not block API startup.
    count = store.load_from_db()
    assert count == 0


def test_record_error_still_returns_the_entry_if_persistence_fails(monkeypatch):
    """The in-memory record — and whatever code path is reporting the failure
    it just caught — must not be lost because the database write failed."""
    store = DiagnosticErrorStore(max_errors=500)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr("app.db.store.session_scope", _boom)

    entry = store.record_error(error="Something broke", service="autopilot")

    assert entry is not None
    assert store.errors[-1].id == entry.id


def test_most_recent_errors_load_first_when_over_the_cap():
    # This table is shared with every other test in this session (the test DB
    # resets once per session, not per test — see conftest.py), so a small
    # max_errors here would pick up whatever sibling tests already wrote with
    # a "now" timestamp newer than any fixed date this test could pick. A
    # store this test owns end-to-end, with unique ids, sidesteps that: it
    # loads everything and checks its OWN three rows' relative order, rather
    # than asserting a hard cap count against a table it doesn't fully own.
    import uuid
    from dataclasses import asdict

    from app.db.store import upsert_entity
    from app.services.observability import DiagnosticError

    run = uuid.uuid4().hex[:8]
    ids = [f"err_order_{run}_{i}" for i in range(3)]
    timestamps = [
        "2020-01-01T00:00:00+00:00",
        "2020-01-02T00:00:00+00:00",
        "2020-01-03T00:00:00+00:00",
    ]

    with session_scope() as db:
        for entry_id, ts in zip(ids, timestamps):
            upsert_entity(
                db,
                "diagnostic_error",
                asdict(DiagnosticError(
                    id=entry_id,
                    timestamp=ts,
                    severity="error",
                    service="autopilot",
                    application_id=None,
                    stage="APPLY",
                    error=f"error for {entry_id}",
                    retries=0,
                    status="open",
                )),
            )

    store = DiagnosticErrorStore(max_errors=10_000)
    store.load_from_db()

    positions = {e.id: i for i, e in enumerate(store.errors)}
    assert ids[0] in positions and ids[1] in positions and ids[2] in positions
    # load_from_db reverses to oldest-first (matching how record_error
    # appends), so the earliest timestamp must come first among these three.
    assert positions[ids[0]] < positions[ids[1]] < positions[ids[2]]
