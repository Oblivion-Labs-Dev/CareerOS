"""Autopilot Self-Healing Code-Fix Pipeline powered by Qwen.

After a batch completes with failures, this module:
1. Collects failure diagnostics (errors, tracebacks, DOM state)
2. Reads the current source code of the executor
3. Asks Qwen to generate a targeted code patch
4. Validates the patch (syntax check)
5. Backs up the original file
6. Applies the patch
7. Hot-reloads the module
8. Re-queues failed jobs for retry
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import shutil
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.store import new_id, now_iso, session_scope
from app.services.application_assistant.llm_client import create_llm_client
from app.services.application_assistant.persistence import (
    get_settings,
    list_autopilot_jobs,
    save_autopilot_job,
)

logger = logging.getLogger("career_os.autopilot_self_healer")

EXECUTOR_PATH = Path(__file__).parent / "playwright_autopilot_executor.py"
BACKUP_DIR = Path(__file__).resolve().parents[3] / "data" / "self_healing_backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

MAX_HEAL_ROUNDS = 3
# AI may analyze failures, but it must not rewrite the live submitter unless an
# operator explicitly enables that capability in the environment.
ALLOW_AI_SOURCE_PATCHES = os.getenv("AA_SELF_HEAL_APPLY_PATCHES", "false").strip().lower() in {"1", "true", "yes"}

SELF_HEALING_SYSTEM_PROMPT = """You are Qwen, the elite self-healing code-fix engine inside CareerOS Autopilot.

You are given:
1. The full current source code of `playwright_autopilot_executor.py`
2. A bundle of failure diagnostics from recent batch runs (error messages, tracebacks, DOM snapshots)

Your task:
- Analyze the failures and determine what code change in the executor would fix them.
- Generate a MINIMAL, TARGETED Python code patch.
- The patch must be syntactically valid Python.
- Do NOT rewrite the entire file. Only return the specific functions or lines that need to change.

Return your response in this exact JSON format:
{
  "analysis": "Brief explanation of the root cause",
  "fixDescription": "What the patch changes and why",
  "patchType": "function_replace",
  "targetFunction": "function_name_to_replace",
  "patchedCode": "the complete replacement function code",
  "confidence": 0.85
}

If the error is NOT fixable by code changes (e.g., network issue, ATS blocking, CAPTCHA), return:
{
  "analysis": "Explanation",
  "fixDescription": "Not a code issue",
  "patchType": "no_fix",
  "confidence": 0.0
}

Rules:
- Never remove safety checks or submission guards
- Never bypass Qwen pre/post submission verification
- Preserve all existing function signatures
- Keep all imports intact
- The patched code must be a complete, drop-in function replacement
"""


class SelfHealingState:
    """Tracks the current state of self-healing for status reporting."""

    def __init__(self) -> None:
        self.status: str = "idle"  # idle | analyzing | patching | requeuing | running
        self.current_round: int = 0
        self.max_rounds: int = MAX_HEAL_ROUNDS
        self.last_patch_summary: str = ""
        self.patches_applied: int = 0
        self.patch_history: list[dict[str, Any]] = []
        self.last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "currentRound": self.current_round,
            "maxRounds": self.max_rounds,
            "lastPatchSummary": self.last_patch_summary,
            "patchesApplied": self.patches_applied,
            "lastError": self.last_error,
            "patchHistory": self.patch_history[-10:],
        }

    def reset(self) -> None:
        self.status = "idle"
        self.current_round = 0
        self.last_error = ""


# Module-level singleton state
_heal_state = SelfHealingState()


def get_self_healing_state() -> SelfHealingState:
    return _heal_state


def collect_failure_diagnostics(failed_jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Collect all relevant failure info from a list of failed autopilot jobs."""
    diagnostics: list[dict[str, Any]] = []
    for job in failed_jobs:
        diag = {
            "jobId": job.get("id"),
            "company": job.get("company"),
            "title": job.get("title"),
            "applicationUrl": job.get("applicationUrl"),
            "error": job.get("lastError"),
            "errorType": job.get("lastErrorType"),
            "aiExplanation": job.get("aiExplanation"),
            "attemptCount": job.get("attemptCount", 0),
            "checkpointHistory": (job.get("checkpointHistory") or [])[-5:],
            "submissionEvidence": job.get("submissionEvidence"),
        }
        diagnostics.append(diag)

    # Group errors by type for pattern detection
    error_types: dict[str, int] = {}
    for d in diagnostics:
        et = d.get("errorType") or "UNKNOWN"
        error_types[et] = error_types.get(et, 0) + 1

    return {
        "failedCount": len(failed_jobs),
        "errorTypeDistribution": error_types,
        "diagnostics": diagnostics[:10],  # Cap at 10 to avoid token overflow
        "collectedAt": now_iso(),
    }


def _read_executor_source() -> str:
    """Read the current source code of the executor module."""
    if EXECUTOR_PATH.exists():
        return EXECUTOR_PATH.read_text(encoding="utf-8")
    return ""


def _backup_executor() -> str:
    """Create a timestamped backup of the executor before patching."""
    if not EXECUTOR_PATH.exists():
        return ""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"playwright_autopilot_executor_{ts}.py.bak"
    shutil.copy2(EXECUTOR_PATH, backup_path)
    logger.info("Backed up executor to %s", backup_path)
    return str(backup_path)


def _validate_patch(patched_code: str) -> bool:
    """Validate that the patched code is syntactically correct Python."""
    try:
        compile(patched_code, "<patch>", "exec")
        return True
    except SyntaxError as e:
        logger.error("Patch syntax validation failed: %s", e)
        return False


def _apply_function_patch(source: str, target_function: str, patched_code: str) -> str | None:
    """Replace a specific function in the source code with the patched version.

    Returns the new full source code, or None if the function wasn't found.
    """
    # Find the function definition
    pattern = rf"^(async\s+)?def\s+{re.escape(target_function)}\s*\("
    match = re.search(pattern, source, re.MULTILINE)
    if not match:
        logger.error("Target function '%s' not found in source", target_function)
        return None

    func_start = match.start()

    # Find the end of the function by tracking indentation
    lines = source[func_start:].split("\n")
    if not lines:
        return None

    # Get the indentation of the def line
    first_line = lines[0]
    base_indent = len(first_line) - len(first_line.lstrip())

    func_end_offset = len(lines[0]) + 1  # +1 for newline
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            func_end_offset += len(line) + 1
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= base_indent and stripped:
            break
        func_end_offset += len(line) + 1

    func_end = func_start + func_end_offset

    # Ensure patched code has correct indentation
    indent = " " * base_indent
    patched_lines = patched_code.strip().split("\n")
    if patched_lines:
        patch_indent = 0
        for ch in patched_lines[0]:
            if ch == " ":
                patch_indent += 1
            else:
                break
        adjusted = []
        for pl in patched_lines:
            stripped_pl = pl[patch_indent:] if len(pl) >= patch_indent else pl.lstrip()
            adjusted.append(indent + stripped_pl)
        patched_code = "\n".join(adjusted) + "\n\n"

    new_source = source[:func_start] + patched_code + source[func_end:]
    return new_source


def _hot_reload_executor() -> bool:
    """Hot-reload the playwright_autopilot_executor module after patching."""
    try:
        import app.services.application_assistant.playwright_autopilot_executor as executor_mod
        importlib.reload(executor_mod)
        logger.info("Hot-reloaded playwright_autopilot_executor module")
        return True
    except Exception as e:
        logger.error("Failed to hot-reload executor module: %s", e)
        return False


def requeue_failed_jobs(failed_jobs: list[dict[str, Any]]) -> int:
    """Reset failed jobs back to QUEUED status for retry."""
    count = 0
    with session_scope() as db:
        for job in failed_jobs:
            job["status"] = "QUEUED"
            job["lastError"] = None
            job["lastErrorType"] = None
            job["attemptCount"] = 0
            job["lockedBy"] = None
            job["lockedAt"] = None
            job["lockExpiresAt"] = None
            job["queuedAt"] = now_iso()
            save_autopilot_job(db, job)
            count += 1
    logger.info("Re-queued %d failed jobs for self-healing retry", count)
    return count


async def ask_qwen_for_code_fix(
    error_bundle: dict[str, Any],
    source_code: str,
) -> dict[str, Any]:
    """Send failure diagnostics + source code to Qwen and get a code patch."""
    with session_scope() as db:
        settings = get_settings(db)

    llm = create_llm_client(settings)
    if not llm or not llm.enabled:
        return {"patchType": "no_fix", "analysis": "LLM not configured", "confidence": 0.0}

    truncated_source = source_code[:12000] if len(source_code) > 12000 else source_code

    prompt = (
        "The CareerOS Autopilot just completed a batch of job applications and some failed.\n\n"
        "## Failure Diagnostics\n"
        f"```json\n{json.dumps(error_bundle, indent=2)[:4000]}\n```\n\n"
        "## Current Executor Source Code (`playwright_autopilot_executor.py`)\n"
        f"```python\n{truncated_source}\n```\n\n"
        "Analyze the failures and generate a targeted code fix. "
        "Return your response as the specified JSON format."
    )

    try:
        result = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            system=SELF_HEALING_SYSTEM_PROMPT,
        )
        raw = result.get("data") or result.get("text") or ""
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            parsed = json.loads(match.group(0))
            return parsed
        return {"patchType": "no_fix", "analysis": "Could not parse Qwen response", "confidence": 0.0}
    except Exception as e:
        logger.error("Qwen code-fix request failed: %s", e)
        return {"patchType": "no_fix", "analysis": f"LLM error: {e}", "confidence": 0.0}


async def run_self_healing_cycle(
    failed_jobs: list[dict[str, Any]],
    log_event_fn: Any = None,
    max_rounds: int = MAX_HEAL_ROUNDS,
) -> dict[str, Any]:
    """Execute the self-healing loop: diagnose -> patch -> reload -> retry.

    Returns a summary dict with results from each round.
    """
    state = get_self_healing_state()
    state.max_rounds = max_rounds
    state.status = "analyzing"
    state.current_round = 0

    rounds_log: list[dict[str, Any]] = []

    def _log(msg: str, level: str = "info") -> None:
        if log_event_fn:
            log_event_fn(msg, level=level)
        getattr(logger, level, logger.info)(msg)

    _log(f"Self-healing cycle started — {len(failed_jobs)} failed job(s), max {max_rounds} rounds")

    current_failures = list(failed_jobs)

    for round_num in range(1, max_rounds + 1):
        state.current_round = round_num
        state.status = "analyzing"
        round_result: dict[str, Any] = {"round": round_num, "status": "started"}

        _log(f"Self-healing round {round_num}/{max_rounds}: Collecting failure diagnostics...")

        # 1. Collect diagnostics
        error_bundle = collect_failure_diagnostics(current_failures)

        # 2. Read current source
        source_code = _read_executor_source()
        if not source_code:
            _log("Cannot read executor source code — aborting self-healing", level="error")
            state.status = "idle"
            state.last_error = "Source code not readable"
            round_result["status"] = "error"
            round_result["error"] = "Source code not readable"
            rounds_log.append(round_result)
            break

        # 3. Ask Qwen for a fix
        state.status = "analyzing"
        _log(f"Round {round_num}: Asking Qwen to analyze {len(current_failures)} failure(s) and generate code fix...")
        patch_response = await ask_qwen_for_code_fix(error_bundle, source_code)

        patch_type = patch_response.get("patchType", "no_fix")
        confidence = patch_response.get("confidence", 0.0)
        analysis = patch_response.get("analysis", "")
        fix_desc = patch_response.get("fixDescription", "")

        _log(f"Round {round_num}: Qwen analysis: {analysis[:200]}")
        round_result["analysis"] = analysis
        round_result["confidence"] = confidence

        if patch_type == "no_fix" or confidence < 0.3:
            _log(f"Round {round_num}: Qwen determined no code fix needed (confidence={confidence:.0%}). Stopping.", level="warning")
            round_result["status"] = "no_fix"
            rounds_log.append(round_result)
            break

        if not ALLOW_AI_SOURCE_PATCHES:
            _log(
                f"Round {round_num}: AI diagnosis is ready for review; live source changes are disabled.",
                level="warning",
            )
            round_result["status"] = "review_required"
            round_result["fixDescription"] = fix_desc
            round_result["targetFunction"] = patch_response.get("targetFunction", "")
            rounds_log.append(round_result)
            state.last_patch_summary = (fix_desc or analysis)[:200]
            break

        # 4. Validate the patch
        state.status = "patching"
        patched_code = patch_response.get("patchedCode", "")
        target_function = patch_response.get("targetFunction", "")

        if not patched_code or not target_function:
            _log(f"Round {round_num}: Qwen returned empty patch or missing target function", level="warning")
            round_result["status"] = "invalid_patch"
            rounds_log.append(round_result)
            continue

        if not _validate_patch(patched_code):
            _log(f"Round {round_num}: Patch failed syntax validation — skipping", level="error")
            round_result["status"] = "syntax_error"
            rounds_log.append(round_result)
            continue

        # 5. Backup original
        backup_path = _backup_executor()
        round_result["backupPath"] = backup_path
        _log(f"Round {round_num}: Backed up executor to {backup_path}")

        # 6. Apply the patch
        new_source = _apply_function_patch(source_code, target_function, patched_code)
        if not new_source:
            _log(f"Round {round_num}: Could not locate function '{target_function}' in source — skipping", level="error")
            round_result["status"] = "function_not_found"
            rounds_log.append(round_result)
            continue

        if not _validate_patch(new_source):
            _log(f"Round {round_num}: Full-file syntax check failed after patching — reverting", level="error")
            if backup_path:
                shutil.copy2(backup_path, EXECUTOR_PATH)
            round_result["status"] = "full_syntax_error"
            rounds_log.append(round_result)
            continue

        # Write the patched file
        EXECUTOR_PATH.write_text(new_source, encoding="utf-8")
        _log(f"Round {round_num}: Applied patch to '{target_function}' — {fix_desc[:150]}")

        # 7. Hot-reload
        if not _hot_reload_executor():
            _log(f"Round {round_num}: Hot-reload failed — reverting to backup", level="error")
            if backup_path:
                shutil.copy2(backup_path, EXECUTOR_PATH)
                _hot_reload_executor()
            round_result["status"] = "reload_failed"
            rounds_log.append(round_result)
            continue

        state.patches_applied += 1
        state.last_patch_summary = fix_desc[:200]

        patch_entry = {
            "id": new_id("patch_"),
            "round": round_num,
            "targetFunction": target_function,
            "analysis": analysis[:300],
            "fixDescription": fix_desc[:300],
            "confidence": confidence,
            "backupPath": backup_path,
            "appliedAt": now_iso(),
        }
        state.patch_history.append(patch_entry)

        # 8. Re-queue failed jobs
        state.status = "requeuing"
        requeued = requeue_failed_jobs(current_failures)
        _log(f"Round {round_num}: Re-queued {requeued} job(s) for retry with patched code")
        round_result["requeued"] = requeued
        round_result["status"] = "patch_applied"
        round_result["fixDescription"] = fix_desc
        rounds_log.append(round_result)

        # Signal ready for runner to re-process — the batch loop picks up QUEUED jobs
        state.status = "running"
        break

    state.status = "idle"

    summary = {
        "totalRounds": len(rounds_log),
        "patchesApplied": state.patches_applied,
        "lastPatchSummary": state.last_patch_summary,
        "rounds": rounds_log,
    }
    _log(f"Self-healing cycle complete: {state.patches_applied} patch(es) applied across {len(rounds_log)} round(s)")
    return summary
