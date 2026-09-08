import asyncio

import pytest

from app.services.application_assistant import autopilot_self_healer as healer
from app.services.application_assistant.healing_response import parse_healing_response


@pytest.mark.parametrize("raw", [
    {"patchType": "no_fix", "analysis": "Expired posting", "confidence": 0.9},
    '```json\n{"patchType":"no_fix","analysis":"Expired posting","confidence":0.9}\n```',
])
def test_accepts_structured_and_fenced_diagnoses(raw):
    assert parse_healing_response({"success": True, "data": raw})["patchType"] == "no_fix"


@pytest.mark.parametrize("result", [
    {"success": False, "error": "Request timed out"},
    {"data": "{ broken JSON }"},
    {"data": {"patchType": "no_fix", "analysis": "x", "confidence": "high"}},
    {"data": {"patchType": "function_replace", "analysis": "x", "confidence": float("nan")}},
])
def test_invalid_diagnosis_is_an_error(result):
    with pytest.raises(ValueError):
        parse_healing_response(result)


def test_cycle_reports_diagnosis_failure_and_no_historical_patches(monkeypatch):
    state = healer.SelfHealingState()
    state.patches_applied = 2
    monkeypatch.setattr(healer, "_heal_state", state)
    monkeypatch.setattr(healer, "_read_executor_source", lambda: "def execute(): pass")

    async def failed(*args):
        return {"patchType": "error", "analysis": "Invalid JSON response", "confidence": 0.0}

    monkeypatch.setattr(healer, "ask_qwen_for_code_fix", failed)
    result = asyncio.run(healer.run_self_healing_cycle([{"id": "job-1"}]))
    assert result["patchesApplied"] == 0
    assert state.patches_applied == 2
    assert result["rounds"][0]["status"] == "diagnosis_failed"
    assert result["lastError"] == "Invalid JSON response"
    assert state.status == "idle"


def test_diagnosis_does_not_write_live_source_by_default(monkeypatch):
    monkeypatch.setattr(healer, "_heal_state", healer.SelfHealingState())
    monkeypatch.setattr(healer, "ALLOW_AI_SOURCE_PATCHES", False)
    monkeypatch.setattr(healer, "_read_executor_source", lambda: "def execute(): pass")

    async def diagnosis(*args):
        return {"patchType": "function_replace", "analysis": "Missing field", "confidence": 0.9,
                "targetFunction": "execute", "patchedCode": "def execute(): return 1"}

    monkeypatch.setattr(healer, "ask_qwen_for_code_fix", diagnosis)
    monkeypatch.setattr(healer, "_backup_executor", lambda: pytest.fail("Must not write source"))
    result = asyncio.run(healer.run_self_healing_cycle([{"id": "job-1"}]))
    assert result["rounds"][0]["status"] == "review_required"
    assert result["patchesApplied"] == 0


def test_post_batch_healing_excludes_failures_from_other_runs(monkeypatch):
    from contextlib import contextmanager

    from app.services.application_assistant import autopilot_runner as runner_module

    @contextmanager
    def session():
        yield None

    runner = runner_module.AutopilotRunner()
    monkeypatch.setattr(runner_module, "session_scope", session)
    monkeypatch.setattr(runner_module, "list_autopilot_jobs", lambda db: [
        {"id": "old-failure", "status": "FAILED", "lastAttemptRunId": "previous"},
    ])

    async def forbidden(**kwargs):
        pytest.fail("Unrelated failed applications must not be retried")

    monkeypatch.setattr(healer, "run_self_healing_cycle", forbidden)
    asyncio.run(runner._trigger_post_batch_self_healing("current"))
