"""Tests for career-ops / ai-tracker ports."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.application_assistant.greenhouse_schema import (
    enrich_field_from_schema,
    parse_greenhouse_url,
)
from app.services.job_search.posting_legitimacy import check_posting_legitimacy
from app.services.market_trends import market_trends_summary
from app.services.safe_write import atomic_write


def test_parse_greenhouse_url() -> None:
    assert parse_greenhouse_url("https://boards.greenhouse.io/acme/jobs/123") == ("acme", "123")
    assert parse_greenhouse_url("https://example.com/jobs/1") is None


def test_enrich_field_from_schema_merges_options() -> None:
    schema = {
        "question_1": {
            "label": "Work authorization",
            "fieldType": "select-one",
            "required": True,
            "options": ["Yes", "No", "Need sponsorship"],
        }
    }
    label, field_type, options, enriched = enrich_field_from_schema(
        field_id="question_1",
        label="Question 1",
        field_type="text",
        options=[],
        schema=schema,
    )
    assert enriched is True
    assert label == "Work authorization"
    assert field_type == "select-one"
    assert options == ["Yes", "No", "Need sponsorship"]


def test_posting_legitimacy_flags_payment_scam() -> None:
    result = check_posting_legitimacy(
        title="Easy money role",
        description="Send $500 training fee via crypto. WhatsApp only.",
        url="https://example.com",
        company="Unknown",
    )
    assert result["verdict"] == "suspicious"
    assert result["signals"]


def test_posting_legitimacy_trusted_greenhouse() -> None:
    result = check_posting_legitimacy(
        title="Senior Software Engineer",
        description="We offer health insurance, 401k, and equal opportunity employment. "
        "Build distributed systems on greenhouse.io careers page with a detailed team mission.",
        url="https://boards.greenhouse.io/acme/jobs/1",
        company="Acme Corp",
    )
    assert result["verdict"] in {"trusted", "caution"}


def test_market_trends_loads_us_series() -> None:
    summary = market_trends_summary(country="US")
    if summary["available"]:
        assert summary["latestShare"] is not None
        assert len(summary["series"]) >= 2
    else:
        pytest.skip("AI_posting.csv not available in test environment")


def test_atomic_write_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "outcome.md"
    atomic_write(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    atomic_write(target, "updated", backup=True)
    assert target.read_text(encoding="utf-8") == "updated"
