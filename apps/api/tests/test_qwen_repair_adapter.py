from __future__ import annotations

import pytest
from app.services.repair.self_healing_prompt import SELF_HEALING_SYSTEM_PROMPT
from app.services.repair.agent import get_agent_adapter
from app.services.repair.qwen_adapter import QwenCodingAgentAdapter
from app.services.repair.types import RepairTask, AgentWorkspace, AgentRun


def test_self_healing_system_prompt_structure():
    assert "CareerOS Self-Healing Agent" in SELF_HEALING_SYSTEM_PROMPT
    assert "CORE PRINCIPLES" in SELF_HEALING_SYSTEM_PROMPT
    assert "SELF-HEALING LOOP" in SELF_HEALING_SYSTEM_PROMPT
    assert "OUTPUT FORMAT" in SELF_HEALING_SYSTEM_PROMPT


def test_get_agent_adapter_resolution():
    mock_adapter = get_agent_adapter("mock")
    assert mock_adapter.__class__.__name__ == "MockCodingAgentAdapter"

    qwen_adapter = get_agent_adapter("qwen")
    assert isinstance(qwen_adapter, QwenCodingAgentAdapter)


def test_qwen_adapter_prompt_and_execution_mocked(monkeypatch, tmp_path):
    import asyncio

    class FakeLLMClient:
        async def complete(self, prompt: str, system: str = "", response_schema: dict | None = None):
            assert "PREVIOUS FAILED ATTEMPTS" in prompt or "Diagnose" in prompt
            return {
                "success": True,
                "data": {
                    "status": "success",
                    "root_cause": "Typo in service method",
                    "hypothesis": "Fix typo to restore function",
                    "changes": [
                        {
                            "file": "test_service.py",
                            "search": "def broken():",
                            "replace": "def fixed():",
                        }
                    ],
                    "verification": "Ran test suite",
                    "files_changed": ["test_service.py"],
                    "remaining_risk": "None",
                },
            }

    adapter = QwenCodingAgentAdapter(llm_client=FakeLLMClient())
    
    # Mock git operations
    monkeypatch.setattr("app.services.repair.qwen_adapter._git_available", lambda repo: True)
    monkeypatch.setattr("app.services.repair.qwen_adapter._create_worktree", lambda repo, branch, path, run: None)

    task = RepairTask(
        task_id="test-task-123",
        fingerprint="fp123",
        title="Test Error",
        status="processing",
        severity="error",
        component="api",
        exception_message="Broken function error",
        stack_trace="Traceback...",
        suspected_source_files=["test_service.py"],
    )
    workspace = AgentWorkspace(repo_root=str(tmp_path), worktrees_dir=str(tmp_path / "worktrees"))

    # Force worktree path
    monkeypatch.setattr(
        "app.services.repair.qwen_adapter.uuid.uuid4",
        lambda: "testrun12345678",
    )

    # Recreate worktree at expected location
    expected_worktree = tmp_path / "worktrees" / "testrun1"
    expected_worktree.mkdir(parents=True)
    (expected_worktree / "test_service.py").write_text("def broken():\n    return True\n", encoding="utf-8")

    run = asyncio.run(adapter.start_async(task, workspace))

    assert run.status == "completed"
    assert run.root_cause == "Typo in service method"
    assert run.hypothesis == "Fix typo to restore function"
    assert (expected_worktree / "test_service.py").read_text(encoding="utf-8") == "def fixed():\n    return True\n"
