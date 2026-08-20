"""Failure Controller — routes failures across Level 1 (runtime), Level 2 (adaptive UI), and Level 3 (code repair)."""

from __future__ import annotations

import os
from typing import Any

from app.services.application_assistant.adaptive_browser_recovery import attempt_adaptive_browser_recovery
from app.services.application_assistant.failure_taxonomy import FailureContext, FailureType, create_failure_signature
from app.services.application_assistant.persistence import get_kv, set_kv, session_scope
from app.services.application_assistant.process_manager import ProcessManager
from app.services.application_assistant.promotion_manager import PromotionManager
from app.services.application_assistant.repair_agent import QwenRepairAgent
from app.services.application_assistant.validation_runner import ValidationRunner
from app.services.application_assistant.worktree_manager import WorktreeManager

MAX_RUNTIME_RECOVERY_ATTEMPTS = 3
MAX_ADAPTIVE_RECOVERY_ATTEMPTS = 2
MAX_CODE_REPAIR_ATTEMPTS = 2


class FailureController:
    def __init__(self) -> None:
        self.wt_manager = WorktreeManager()
        self.val_runner = ValidationRunner()
        self.prom_manager = PromotionManager()
        self.proc_manager = ProcessManager.get_instance()

    def get_attempt_counts(self, signature: str) -> dict[str, int]:
        with session_scope() as db:
            hist = get_kv(db, f"failure_attempts_{signature}") or {}
            return {
                "runtime": int(hist.get("runtime", 0)),
                "adaptive": int(hist.get("adaptive", 0)),
                "repair": int(hist.get("repair", 0)),
            }

    def increment_attempt_count(self, signature: str, level_key: str) -> None:
        with session_scope() as db:
            hist = get_kv(db, f"failure_attempts_{signature}") or {}
            hist[level_key] = int(hist.get(level_key, 0)) + 1
            set_kv(db, f"failure_attempts_{signature}", hist)

    def record_repair_audit(self, failure: FailureContext, audit_data: dict[str, Any]) -> None:
        with session_scope() as db:
            audits = get_kv(db, "repair_audit_log") or []
            audits.append({
                "failureId": failure.failure_id,
                "signature": create_failure_signature(failure),
                "atsType": failure.ats_type,
                "timestamp": failure.to_dict().get("lastHeartbeatAt"),
                **audit_data,
            })
            if len(audits) > 200:
                audits.pop(0)
            set_kv(db, "repair_audit_log", audits)

    async def handle_failure(self, failure: FailureContext) -> dict[str, Any]:
        """Main failure routing handler executing Level 1 -> Level 2 -> Level 3 recovery."""
        signature = create_failure_signature(failure)
        counts = self.get_attempt_counts(signature)

        # Non-recoverable failures stage immediately
        if failure.failure_type in (FailureType.CAPTCHA, FailureType.AUTH_REQUIRED, FailureType.UNSUPPORTED_QUESTION):
            return {
                "outcome": "STAGED",
                "reason": f"Manual action required for {failure.failure_type.value}",
                "level": 0,
            }

        # Level 1: Runtime Recovery
        if counts["runtime"] < MAX_RUNTIME_RECOVERY_ATTEMPTS:
            self.increment_attempt_count(signature, "runtime")
            return {
                "outcome": "RETRY_RUNTIME",
                "action": "RELOAD_PAGE_RETRY",
                "level": 1,
            }

        # Level 2: Adaptive Browser Recovery
        if counts["adaptive"] < MAX_ADAPTIVE_RECOVERY_ATTEMPTS:
            self.increment_attempt_count(signature, "adaptive")
            rec = await attempt_adaptive_browser_recovery(failure)
            if rec.get("recoveryType") == "RUNTIME_ACTION" and rec.get("actions"):
                return {
                    "outcome": "RETRY_ADAPTIVE",
                    "actions": rec.get("actions"),
                    "level": 2,
                }

        # Level 3: Isolated Code Repair
        if counts["repair"] < MAX_CODE_REPAIR_ATTEMPTS:
            self.increment_attempt_count(signature, "repair")
            repair_res = await self._attempt_code_repair(failure)
            if repair_res.get("success"):
                return {
                    "outcome": "REPAIR_PROMOTED",
                    "commit": repair_res.get("commit"),
                    "level": 3,
                }

        # Staging fallback
        return {
            "outcome": "STAGED",
            "reason": f"Max recovery limits reached for signature {signature}",
            "level": 3,
        }

    async def _attempt_code_repair(self, failure: FailureContext) -> dict[str, Any]:
        """Level 3: Spawns isolated Git worktree, runs Qwen repair agent, validates, and promotes patch."""
        worktree = self.wt_manager.create_repair_worktree(failure.failure_id, failure.running_commit)
        try:
            agent = QwenRepairAgent(worktree.path)
            diagnosis = await agent.run_diagnosis_and_repair(failure)

            val_res = self.val_runner.validate(worktree, failure)
            if not val_res.success:
                self.record_repair_audit(failure, {"promoted": False, "diagnosis": diagnosis, "errors": val_res.errors})
                return {"success": False, "reason": "VALIDATION_FAILED"}

            prom_res = self.prom_manager.promote_worktree_repair(worktree, failure.running_commit)
            if prom_res.promoted:
                self.proc_manager.restart_application_worker()
                self.record_repair_audit(failure, {"promoted": True, "commit": prom_res.commit, "diagnosis": diagnosis})
                return {"success": True, "commit": prom_res.commit}

            self.record_repair_audit(failure, {"promoted": False, "message": prom_res.message})
            return {"success": False, "reason": prom_res.message}
        finally:
            self.wt_manager.remove(worktree)
