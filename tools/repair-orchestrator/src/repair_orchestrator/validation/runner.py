from __future__ import annotations

import subprocess
import time
from typing import Any

from repair_orchestrator.config import settings
from repair_orchestrator.models import ValidationResult, utc_now_iso


def run_validation(commands: list[str] | None = None, repo_root: str | None = None) -> ValidationResult:
    root = repo_root or settings.repair_repo_root
    command_list = commands or [
        item.strip() for item in settings.validation_commands.split(",") if item.strip()
    ]
    results: list[dict[str, Any]] = []
    all_passed = True
    for command in command_list:
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=settings.max_execution_seconds,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            passed = completed.returncode == 0
            all_passed = all_passed and passed
            results.append(
                {
                    "command": command,
                    "passed": passed,
                    "exitCode": completed.returncode,
                    "durationMs": duration_ms,
                    "stdout": completed.stdout[-4000:],
                    "stderr": completed.stderr[-4000:],
                }
            )
        except subprocess.TimeoutExpired as exc:
            all_passed = False
            results.append(
                {
                    "command": command,
                    "passed": False,
                    "exitCode": -1,
                    "durationMs": settings.max_execution_seconds * 1000,
                    "stdout": (exc.stdout or b"").decode("utf-8", errors="replace")[-4000:],
                    "stderr": (exc.stderr or b"").decode("utf-8", errors="replace")[-4000:] or "Timed out",
                }
            )
    regression_present = any("test_" in item["command"] for item in results)
    return ValidationResult(
        passed=all_passed,
        commands=results,
        regressionTestPresent=regression_present,
        completedAt=utc_now_iso(),
    )
