"""Checks a change must pass before it is called validated or promoted.

Shared by the improver (validation in its own worktree) and promotion (the same
checks again on the integrated branch). Everything here runs locally with the
test suite's fakes: `tests/conftest.py` isolates the DB, disables every model
provider and the executor refuses a live submit click outside production, so
no gate can reach an employer or a paid API.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Duplicate-submission and submission-proof protections. A fix that breaks any
# of these is rejected regardless of what it repairs.
SUBMISSION_GUARD_TESTS = (
    "tests/test_duplicate_submission.py",
    "tests/test_submission_idempotency.py",
    "tests/test_identity_duplicate_guard.py",
    "tests/test_autopilot_duplicate_precheck.py",
    "tests/test_submission_confirmation_evidence.py",
    "tests/test_submission_pacing.py",
)
# Production security gates from the production-readiness passes.
SECURITY_GATE_TESTS = (
    "tests/test_hosting_security.py",
    "tests/test_production_requires_auth.py",
    "tests/test_auth_gate.py",
    "tests/test_apply_level_gate.py",
)
OVERNIGHT_TESTS = ("tests/test_overnight_loops.py",)

# Paths no overnight agent may touch (secrets, CI, schema, extension identity,
# the mail sender) — the repair orchestrator's list, plus the overnight system
# itself so the improver can never loosen its own guard rails.
PROTECTED_PREFIXES = (
    ".env",
    ".github/",
    "apps/api/migrations/",
    "apps/api/alembic/",
    "apps/extension/manifest",
    "apps/api/app/services/overnight/",
    "apps/api/tests/test_overnight_",
    "scripts/overnight",
    "AGENTS.md",
    "CLAUDE.md",
)
PROTECTED_NAMES = ("gmail_sender.py", "conftest.py")

# Files where a bug could send an application twice or to the wrong place; a
# change touching any of them gets an independent Codex review.
HIGH_RISK_MARKERS = (
    "autopilot_runner.py",
    "submission_outcome.py",
    "persistence.py",
    "executor",
    "browser_pool.py",
    "submit",
    "routers/application_assistant/autopilot.py",
)

MAX_CHANGED_FILES = 20
MAX_DIFF_BYTES = 50_000


@dataclass
class GateResult:
    name: str
    ok: bool
    detail: str = ""
    output_tail: str = ""


@dataclass
class GateReport:
    results: list[GateResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(r.ok for r in self.results)

    def failed(self) -> list[GateResult]:
        return [r for r in self.results if not r.ok]

    def to_dict(self) -> dict:
        return {"ok": self.ok, "results": [r.__dict__ for r in self.results]}


def check_diff(changed: list[str], diff_bytes: int) -> GateResult:
    """Scope guard rails on a proposed change."""
    problems = []
    if not changed:
        problems.append("no files changed")
    if len(changed) > MAX_CHANGED_FILES:
        problems.append(f"{len(changed)} files changed (max {MAX_CHANGED_FILES})")
    if diff_bytes > MAX_DIFF_BYTES:
        problems.append(f"diff is {diff_bytes} bytes (max {MAX_DIFF_BYTES})")
    for path in changed:
        norm = path.replace("\\", "/")
        if norm.startswith(PROTECTED_PREFIXES) or Path(norm).name.startswith(PROTECTED_NAMES):
            problems.append(f"touches protected path {norm}")
    if changed and not any(p.replace("\\", "/").startswith("apps/api/tests/test_") for p in changed):
        problems.append("no regression test added or changed")
    return GateResult("diff-guardrails", not problems, "; ".join(problems) or f"{len(changed)} files, {diff_bytes} bytes")


def is_high_risk(changed: list[str]) -> bool:
    return any(marker in path.replace("\\", "/") for path in changed for marker in HIGH_RISK_MARKERS)


Runner = Callable[[list[str], Path, float], tuple[int, str]]


def subprocess_runner(cmd: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return 124, out + f"\n[timed out after {timeout:.0f}s]"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_pytest(
    name: str, api_dir: Path, paths: list[str], runner: Runner = subprocess_runner, timeout: float = 900
) -> GateResult:
    existing = [p for p in dict.fromkeys(paths) if (api_dir / p).exists()]
    missing = sorted(set(paths) - set(existing))
    if not existing:
        return GateResult(name, False, f"none of the test files exist: {missing}")
    code, out = runner([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *existing], api_dir, timeout)
    tail = "\n".join(out.strip().splitlines()[-15:])
    detail = tail.splitlines()[-1] if tail else f"exit {code}"
    if missing:
        detail += f" (missing: {', '.join(missing)})"
    return GateResult(name, code == 0, detail, tail)


def run_compile(api_dir: Path, runner: Runner = subprocess_runner) -> GateResult:
    code, out = runner([sys.executable, "-m", "compileall", "-q", "app"], api_dir, 300)
    return GateResult("compileall", code == 0, "app compiles" if code == 0 else out.strip()[-400:])


def standard_gates(api_dir: Path, extra_tests: list[str], runner: Runner = subprocess_runner) -> GateReport:
    """Compile, the change's own tests, submission guards, security gates."""
    report = GateReport()
    report.results.append(run_compile(api_dir, runner))
    if extra_tests:
        report.results.append(run_pytest("change-tests", api_dir, extra_tests, runner))
    report.results.append(run_pytest("submission-guards", api_dir, list(SUBMISSION_GUARD_TESTS), runner))
    report.results.append(run_pytest("security-gates", api_dir, list(SECURITY_GATE_TESTS), runner))
    return report
