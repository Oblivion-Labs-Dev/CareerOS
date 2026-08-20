"""Qwen Local Code Repair Agent — operates exclusively within isolated Git worktree."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from app.services.application_assistant.failure_taxonomy import FailureContext
from app.services.application_assistant.llm_client import create_llm_client
from app.services.application_assistant.persistence import get_settings, session_scope

REPAIR_DIAGNOSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {"type": "string"},
        "confidence": {"type": "number"},
        "rootCause": {"type": "string"},
        "recoveryType": {"type": "string", "enum": ["RUNTIME_ACTION", "CODE_PATCH", "STAGE"]},
        "safeToAutoFix": {"type": "boolean"},
        "affectedFiles": {"type": "array", "items": {"type": "string"}},
        "recommendedAction": {"type": "string"},
        "patchCode": {"type": "string"},
    },
    "required": ["classification", "confidence", "rootCause", "recoveryType", "safeToAutoFix", "affectedFiles", "recommendedAction"],
}

REPAIR_AGENT_SYSTEM_PROMPT = """You are the CareerOS Repair Agent operating inside an isolated Git worktree.
Your goal is to inspect automation failure evidence, diagnose selector or markup changes, and produce a safe, minimal code patch.

Rules:
1. Work ONLY inside the provided worktree directory.
2. Fix the root cause with minimal, reliable changes.
3. Do NOT weaken submission validation or bypass CAPTCHA.
4. Do NOT commit code until validation succeeds.
5. Do NOT modify unrelated code or database schemas.
6. Return a valid JSON report adhering strictly to the response schema.
"""


class RepairAgentTools:
    """Constrained tool execution API for Qwen Repair Agent within a worktree."""

    def __init__(self, worktree_path: str | Path) -> None:
        self.worktree_path = Path(worktree_path).resolve()

    def _resolve(self, rel_path: str) -> Path:
        target = (self.worktree_path / rel_path).resolve()
        if not str(target).startswith(str(self.worktree_path)):
            raise ValueError(f"Path escape attempt blocked: {rel_path}")
        return target

    def read_file(self, rel_path: str) -> str:
        target = self._resolve(rel_path)
        if not target.is_file():
            raise FileNotFoundError(f"File not found: {rel_path}")
        return target.read_text(encoding="utf-8", errors="replace")

    def write_file(self, rel_path: str, content: str) -> None:
        target = self._resolve(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def list_files(self, rel_path: str = "") -> list[str]:
        target = self._resolve(rel_path)
        if not target.is_dir():
            return []
        return [str(p.relative_to(self.worktree_path)) for p in target.glob("**/*") if p.is_file()]

    def search_repo(self, query: str) -> list[str]:
        matches: list[str] = []
        for root, _, files in os.walk(self.worktree_path):
            for file in files:
                if file.endswith((".py", ".ts", ".tsx", ".js", ".json")):
                    p = Path(root) / file
                    try:
                        text = p.read_text(encoding="utf-8", errors="ignore")
                        if query.lower() in text.lower():
                            matches.append(str(p.relative_to(self.worktree_path)))
                    except Exception:
                        pass
        return matches[:20]

    def git_diff(self) -> str:
        res = subprocess.run(
            ["git", "diff"],
            cwd=str(self.worktree_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return res.stdout.strip()


class QwenRepairAgent:
    def __init__(self, worktree_path: str | Path) -> None:
        self.worktree_path = Path(worktree_path).resolve()
        self.tools = RepairAgentTools(self.worktree_path)

    async def run_diagnosis_and_repair(self, failure: FailureContext) -> dict[str, Any]:
        """Query Qwen for root-cause diagnosis and patch recommendation."""
        with session_scope() as db:
            settings = get_settings(db)
            client = create_llm_client(settings)

        if not client.enabled:
            return {
                "classification": failure.failure_type.value,
                "confidence": 0.0,
                "rootCause": "Local Qwen LLM unavailable",
                "recoveryType": "STAGE",
                "safeToAutoFix": False,
                "affectedFiles": [],
                "recommendedAction": "Stage application for manual review",
            }

        prompt = (
            f"Failure ID: {failure.failure_id}\n"
            f"Failure Type: {failure.failure_type.value}\n"
            f"ATS: {failure.ats_type} ({failure.adapter_name})\n"
            f"Error Message: {failure.error_message}\n"
            f"Stack Trace: {failure.stack_trace[:500]}\n"
            f"Current Step: {failure.current_step}\n"
            f"Failed Selectors: {failure.selector_attempts}\n"
            f"Running Commit: {failure.running_commit}\n"
        )

        res = await client.complete(prompt, system=REPAIR_AGENT_SYSTEM_PROMPT, response_schema=REPAIR_DIAGNOSIS_SCHEMA)
        if res.get("success") and isinstance(res.get("data"), dict):
            diagnosis = res["data"]
            # Apply recommended patch if provided
            patch_code = diagnosis.get("patchCode")
            affected_files = diagnosis.get("affectedFiles") or []
            if patch_code and len(affected_files) == 1:
                try:
                    self.tools.write_file(affected_files[0], patch_code)
                except Exception as exc:
                    diagnosis["patchError"] = str(exc)
            return diagnosis

        return {
            "classification": failure.failure_type.value,
            "confidence": 0.0,
            "rootCause": "Malformed Qwen response",
            "recoveryType": "STAGE",
            "safeToAutoFix": False,
            "affectedFiles": [],
            "recommendedAction": "Stage application",
        }
