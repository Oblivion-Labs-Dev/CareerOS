"""The JSON expression indexes only work if the query repeats the indexed
expression exactly; a bound `?` path silently turned every one into a scan."""

import pytest
from sqlalchemy import text

from app.db.store import EntityStore, SessionLocal, _configure_sqlite, json_field


def _plan(query) -> str:
    sql = str(query.statement.compile(compile_kwargs={"literal_binds": True}))
    with SessionLocal() as db:
        return " ".join(str(row) for row in db.execute(text("EXPLAIN QUERY PLAN " + sql)).fetchall())


def test_status_lookup_searches_the_expression_index():
    _configure_sqlite()
    with SessionLocal() as db:
        query = db.query(EntityStore.id).filter(
            EntityStore.entity_type == "aa_autopilot_job", json_field("$.status") == "QUEUED"
        )
    plan = _plan(query)
    assert "ix_entities_status" in plan and "<expr>" in plan, plan


def test_added_to_assistant_lookup_range_scans_its_index():
    _configure_sqlite()
    with SessionLocal() as db:
        query = db.query(EntityStore.id).filter(
            EntityStore.entity_type == "aa_discovered_job", json_field("$.addedToAssistant") > 0
        )
    plan = _plan(query)
    assert "ix_entities_added_to_assistant" in plan and "<expr>" in plan, plan


@pytest.mark.parametrize("path", ["$.x') OR 1=1 --", "status", "$..a", "$.a b"])
def test_json_field_refuses_anything_but_a_plain_path(path):
    with pytest.raises(ValueError):
        json_field(path)
