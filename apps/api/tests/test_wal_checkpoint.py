"""The SQLite WAL is checkpointed and truncated, and a blocking reader is reported (#100).

Runs against the real (temporary) SQLite database the test suite uses.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import text

from app.db.store import WAL_SIZE_LIMIT_BYTES, checkpoint_wal, delete_entity, engine, session_scope, upsert_entity

_IDS = [f"wal_test_{i}" for i in range(200)]


def _write_rows() -> None:
    with session_scope() as db:
        for entity_id in _IDS:
            upsert_entity(db, "wal_test", {"id": entity_id, "blob": "z" * 4000})


@pytest.fixture()
def cleanup():
    yield
    with session_scope() as db:
        for entity_id in _IDS:
            delete_entity(db, "wal_test", entity_id)
    checkpoint_wal()


@pytest.mark.skipif("sqlite" not in str(engine.url), reason="SQLite WAL behaviour")
def test_connections_cap_the_wal_size() -> None:
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_size_limit")).scalar() == WAL_SIZE_LIMIT_BYTES


@pytest.mark.skipif("sqlite" not in str(engine.url), reason="SQLite WAL behaviour")
def test_checkpoint_truncates_the_wal(cleanup) -> None:
    _write_rows()
    result = checkpoint_wal()
    assert result is not None and not result["busy"]
    assert result["checkpointedFrames"] == result["logFrames"]
    assert result["walBytes"] == 0


@pytest.mark.skipif("sqlite" not in str(engine.url), reason="SQLite WAL behaviour")
def test_open_reader_blocking_the_checkpoint_is_reported(cleanup, caplog) -> None:
    _write_rows()
    checkpoint_wal()
    reader = engine.raw_connection()
    try:
        cursor = reader.cursor()
        cursor.execute("BEGIN")
        cursor.execute("SELECT count(*) FROM entities").fetchone()  # holds a read snapshot
        _write_rows()  # frames the reader's snapshot predates
        with caplog.at_level(logging.INFO, logger="career_os.db"):
            result = checkpoint_wal()
        assert result["busy"] or result["checkpointedFrames"] < result["logFrames"]
        assert "WAL checkpoint blocked by an open reader" in caplog.text
    finally:
        reader.rollback()
        reader.close()
    assert checkpoint_wal()["walBytes"] == 0
