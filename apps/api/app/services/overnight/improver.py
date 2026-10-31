"""Loop B — one bounded improvement at a time, isolated from the live worker.

A cycle:

1. Read jobs (read-only), group them by root cause and pick the highest-ranked
   code-fixable group (`grouping`). Groups that already failed twice are
   skipped; groups waiting on the user's answers are only reported.
2. Create a fresh git worktree and branch off the production-readiness branch.
   The live worker's code is never touched: the agent edits only that worktree.
3. Run ONE headless coding agent (`claude -p`) with a bounded prompt: reproduce
   the failure from the representative job's recorded evidence as a regression
   test, make one focused fix, no browser, no network, no submitting.
4. Check the diff against scope guard rails, run the change's tests, the
   duplicate-submission suites and the production security gates
   (`gates.standard_gates`). Changes to submission-path files also get one
   Codex review through codex-bridge.
5. Pass: commit on the branch and record the fix as *validated, awaiting
   promotion*. Fail: remove the worktree and branch, record the blocker, count
   the attempt against the group.

Every step is checkpointed to `improver.json`; a crash mid-step is detected on
the next start and the half-done attempt is cleaned up and recorded. While an
agent runs, the improver also holds nightly-evolution's engine lock so only one
improvement lane edits code at a time.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.services.overnight import gates
from app.services.overnight.api_client import read_jobs
from app.services.overnight.grouping import Group, build_groups, next_fixable
from app.services.overnight.state import (
    LockHeld,
    StateStore,
    acquire_file_lock,
    memory_snapshot,
    now_iso,
    release_file_lock,
)

LOOP = "improver"
REPO_ROOT = Path(__file__).resolve().parents[5]

STEP_SELECTED = "selected"
STEP_WORKTREE = "worktree"
STEP_AGENT = "agent"
STEP_VALIDATING = "validating"
STEP_REVIEW = "review"
FINAL_STEPS = ("validated", "blocked", "no-change")

# Fields from a job that help an agent reproduce a failure. Nothing personal:
# answers, resumes and contact details stay out of the prompt.
_EVIDENCE_KEYS = ("id", "company", "title", "applicationUrl", "status", "lastError",
                  "lastErrorType", "skipReason", "technicalFailure", "attemptCount")


@dataclass
class ImproverConfig:
    repo_root: Path = REPO_ROOT
    base_ref: str = "HEAD"
    worktrees_dir: Path | None = None
    agent_timeout_s: float = 1500.0
    review_timeout_s: float = 900.0
    min_free_ram_mb: int = 1500
    max_attempts: int = 2
    min_group_size: int = 2
    claude_bin: str = "claude"
    codex_bin: str = "codex-bridge"
    jobs_reader: Callable[[], list[dict[str, Any]]] = read_jobs
    runner: gates.Runner = gates.subprocess_runner
    evolution_lock: Path | None = None

    def __post_init__(self) -> None:
        self.repo_root = Path(self.repo_root)
        if self.worktrees_dir is None:
            self.worktrees_dir = self.repo_root.parent / "CareerOS-worktrees"
        if self.evolution_lock is None:
            self.evolution_lock = _git_common_dir(self.repo_root) / "evolution" / "engine.lock"


def _git_common_dir(repo: Path) -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=str(repo),
                             capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        out = ""
    path = Path(out) if out else repo / ".git"
    return path if path.is_absolute() else (repo / path).resolve()


def slug(signature: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", signature.lower()).strip("-")[:48] or "group"


def _git(cfg: ImproverConfig, args: list[str], cwd: Path | None = None, timeout: float = 120) -> tuple[int, str]:
    return cfg.runner(["git", *args], cwd or cfg.repo_root, timeout)


def build_prompt(group: Group, samples: list[dict[str, Any]]) -> str:
    evidence = [{k: s.get(k) for k in _EVIDENCE_KEYS if s.get(k) is not None}
                | {"recentCheckpoints": [str((c or {}).get("details") or "")[:300]
                                         for c in (s.get("checkpointHistory") or [])[-5:]]}
                for s in samples]
    return f"""You are fixing ONE recurring Auto Apply failure in CareerOS, overnight and unattended.

Failure group: {group.signature}
Category: {group.category} | ATS: {group.ats} | eligible applications affected: {group.eligible}
Recorded evidence from the representative application and a few siblings:
{json.dumps(evidence, indent=2, default=str)[:6000]}

Do exactly this, in this git worktree only:
1. Read AGENTS.md, then find the code path that produces this failure.
2. Reproduce it as a regression test under apps/api/tests/ that FAILS before your fix. Build
   the input from the recorded evidence above (form HTML fixture, label text, error string);
   reach state through production code paths, never hand-seeded impossible state.
3. Make ONE focused fix so the test passes and the siblings would pass too. Keep the diff small.
4. Run only the tests you touched plus the closest existing suite, with
   `python -m pytest -q <files>` from apps/api. Do not run the full suite.

Hard rules (a violation discards the change):
- Never open a browser, start the app, call the network, or submit or requeue anything.
- Never weaken a duplicate-submission, submit-proof, eligibility, rate-limit or bot-protection
  check, and never bypass a CAPTCHA or site protection. Never invent screening answers.
- Do not touch .env files, .github, migrations, the extension manifest, gmail_sender.py,
  conftest.py, AGENTS.md/CLAUDE.md or anything under app/services/overnight.
- Do not commit, push, merge or create branches; the caller does that.
- If no safe code fix exists (the failure is the employer's requirement, bot protection, or
  needs the candidate's input), change nothing and end with one line: BLOCKER: <why>.
End with one line: SUMMARY: <what you changed and why>.
"""


def _parse_claude(out: str) -> dict[str, Any]:
    try:
        data = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
    except (json.JSONDecodeError, IndexError):
        return {"text": out[-2000:], "usage": None}
    text = str(data.get("result") or "")
    return {
        "text": text[-4000:],
        "isError": bool(data.get("is_error")),
        "usage": {
            "costUsd": data.get("total_cost_usd"),
            "turns": data.get("num_turns"),
            "durationMs": data.get("duration_ms"),
            "inputTokens": (data.get("usage") or {}).get("input_tokens"),
            "outputTokens": (data.get("usage") or {}).get("output_tokens"),
        },
    }


def run_agent(cfg: ImproverConfig, worktree: Path, prompt: str) -> dict[str, Any]:
    cmd = [
        cfg.claude_bin, "-p", prompt,
        "--output-format", "json",
        "--permission-mode", "acceptEdits",
        "--allowedTools", "Read,Edit,Write,Grep,Glob,Bash(python -m pytest:*),Bash(git diff:*),Bash(git status:*)",
        "--disallowedTools", "WebFetch,WebSearch,Bash(git push:*),Bash(git commit:*)",
    ]
    code, out = cfg.runner(cmd, worktree, cfg.agent_timeout_s)
    parsed = _parse_claude(out)
    parsed["exitCode"] = code
    return parsed


def run_review(cfg: ImproverConfig, worktree: Path, commit: str, group: Group) -> dict[str, Any]:
    focus = (f"Overnight fix for '{group.signature}'. Check for any path that could submit an "
             "application twice, submit without proof, bypass eligibility or bot protection, or "
             "weaken a test. Prefix each blocking finding with 'BLOCKING:'.")
    code, out = cfg.runner([cfg.codex_bin, "review", "--cd", str(worktree), "--commit", commit,
                            "--prompt", focus], worktree, cfg.review_timeout_s)
    try:
        summary = json.loads(out.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        summary = {"status": "failed", "lastMessage": out[-1500:]}
    message = str(summary.get("lastMessage") or "")
    blocking = [line.strip() for line in message.splitlines() if "BLOCKING:" in line]
    return {
        "status": summary.get("status") if code == 0 else (summary.get("status") or "failed"),
        "blocking": blocking[:10],
        "usage": summary.get("usage"),
        "message": message[-3000:],
        "errors": summary.get("errors"),
    }


def _changed_files(cfg: ImproverConfig, worktree: Path) -> tuple[list[str], int]:
    _git(cfg, ["add", "--intent-to-add", "."], worktree)  # inside the throwaway worktree only
    _, names = _git(cfg, ["diff", "--name-only"], worktree)
    _, diff = _git(cfg, ["diff"], worktree)
    return [n for n in names.splitlines() if n.strip()], len(diff.encode("utf-8", "replace"))


def cleanup(cfg: ImproverConfig, item: dict[str, Any]) -> None:
    worktree = item.get("worktree")
    if worktree and Path(worktree).exists():
        _git(cfg, ["worktree", "remove", "--force", worktree])
        if Path(worktree).exists():
            shutil.rmtree(worktree, ignore_errors=True)
    _git(cfg, ["worktree", "prune"])
    if item.get("branch") and item.get("step") != "validated":
        _git(cfg, ["branch", "-D", item["branch"]])


class Improver:
    def __init__(self, store: StateStore, cfg: ImproverConfig):
        self.store = store
        self.cfg = cfg

    # ---- state helpers ---------------------------------------------------
    def state(self) -> dict[str, Any]:
        doc = self.store.read("improver.json")
        doc.setdefault("history", {})
        doc.setdefault("fixes", [])
        doc.setdefault("usage", {"agentRuns": 0, "reviewRuns": 0, "costUsd": 0.0})
        return doc

    def checkpoint(self, doc: dict[str, Any], **current: Any) -> None:
        doc["current"] = {**(doc.get("current") or {}), **current, "updatedAt": now_iso()}
        self.store.write("improver.json", doc)

    def _finish(self, doc: dict[str, Any], outcome: str, detail: str, **extra: Any) -> dict[str, Any]:
        item = {**(doc.get("current") or {}), **extra, "step": outcome, "detail": detail, "finishedAt": now_iso()}
        sig = item.get("signature")
        hist = doc["history"].setdefault(sig, {"attempts": 0}) if sig else {}
        if sig:
            hist["attempts"] = int(hist.get("attempts") or 0) + (0 if outcome == "validated" else 1)
            hist["lastOutcome"] = outcome
            hist["lastDetail"] = detail[:500]
            if outcome == "validated":
                hist["blocked"] = True  # fixed or pending promotion; do not pick it again
        if outcome != "validated":
            cleanup(self.cfg, item)
            item.pop("worktree", None)
        doc["fixes"].append(item)
        doc["current"] = None
        self.store.write("improver.json", doc)
        self.store.event(LOOP, outcome, f"{sig}: {detail}"[:600], branch=item.get("branch"), commit=item.get("commit"))
        return item

    def recover(self) -> dict[str, Any] | None:
        """A previous improver died mid-attempt: clean up and record it."""
        doc = self.state()
        current = doc.get("current")
        if current and current.get("step") not in FINAL_STEPS:
            return self._finish(doc, "blocked", f"interrupted at step '{current.get('step')}' (process exited)")
        return None

    # ---- grouping --------------------------------------------------------
    def compute_groups(self, jobs: list[dict[str, Any]] | None = None) -> list[Group]:
        jobs = self.cfg.jobs_reader() if jobs is None else jobs
        doc = self.state()
        groups = build_groups(jobs, doc["history"], self.cfg.max_attempts)
        self.store.write("groups.json", {
            "computedAt": now_iso(),
            "groups": [g.to_dict() for g in groups[:200]],
            "totals": {
                "groups": len(groups),
                "eligible": sum(g.eligible for g in groups),
                "codeFixableEligible": sum(g.eligible for g in groups if g.kind == "code" and not g.blocked),
            },
        })
        return groups

    # ---- one cycle -------------------------------------------------------
    def cycle(self) -> dict[str, Any]:
        """Run one bounded improvement. Returns the finished item or a skip note."""
        self.recover()
        if self.store.stop_requested():
            return {"skipped": "stop requested"}
        res = memory_snapshot()
        if "ramAvailableMb" in res and res["ramAvailableMb"] < self.cfg.min_free_ram_mb:
            note = f"only {res['ramAvailableMb']} MB RAM free (need {self.cfg.min_free_ram_mb}); waiting"
            self.store.event(LOOP, "wait", note)
            return {"skipped": note}

        jobs = self.cfg.jobs_reader()
        groups = self.compute_groups(jobs)
        group = next_fixable(groups, self.cfg.min_group_size)
        if group is None:
            self.store.event(LOOP, "idle", "No code-fixable group left above the size threshold")
            return {"skipped": "no fixable group"}

        by_id = {str(j.get("id")): j for j in jobs}
        samples = [by_id[i] for i in group.eligible_ids[:4] if i in by_id]
        doc = self.state()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        branch = f"overnight/fix-{slug(group.signature)}-{stamp}"
        worktree = self.cfg.worktrees_dir / f"overnight-{slug(group.signature)[:32]}-{stamp}"
        self.checkpoint(doc, step=STEP_SELECTED, signature=group.signature, category=group.category,
                        eligible=group.eligible, representative=samples[0].get("id") if samples else None,
                        branch=branch, worktree=str(worktree), startedAt=now_iso())
        self.store.event(LOOP, "selected", f"{group.signature} ({group.eligible} eligible)")

        try:
            acquire_file_lock(self.cfg.evolution_lock, f"careeros overnight improver: {group.signature}"[:120])
        except LockHeld as exc:
            doc["current"] = None
            self.store.write("improver.json", doc)
            self.store.event(LOOP, "wait", f"Another improvement lane is active: {exc}")
            return {"skipped": str(exc)}
        try:
            return self._attempt(doc, group, samples, branch, worktree)
        finally:
            release_file_lock(self.cfg.evolution_lock)

    def _attempt(self, doc, group: Group, samples, branch: str, worktree: Path) -> dict[str, Any]:
        cfg = self.cfg
        _, base = _git(cfg, ["rev-parse", cfg.base_ref])
        base = base.strip()
        self.cfg.worktrees_dir.mkdir(parents=True, exist_ok=True)
        code, out = _git(cfg, ["worktree", "add", "-b", branch, str(worktree), base])
        if code != 0:
            return self._finish(doc, "blocked", f"git worktree add failed: {out.strip()[-300:]}")
        self.checkpoint(doc, step=STEP_WORKTREE, base=base)

        self.checkpoint(doc, step=STEP_AGENT)
        agent = run_agent(cfg, worktree, build_prompt(group, samples))
        usage = doc["usage"]
        usage["agentRuns"] += 1
        usage["costUsd"] = round(usage["costUsd"] + float((agent.get("usage") or {}).get("costUsd") or 0), 4)
        self.checkpoint(doc, agentSummary=agent.get("text", "")[-1200:], agentUsage=agent.get("usage"))
        if agent.get("exitCode") != 0 or agent.get("isError"):
            return self._finish(doc, "blocked", f"agent failed (exit {agent.get('exitCode')}): {agent.get('text', '')[-300:]}")

        changed, diff_bytes = _changed_files(cfg, worktree)
        if not changed:
            blocker = re.search(r"BLOCKER:\s*(.+)", agent.get("text", ""))
            return self._finish(doc, "no-change", blocker.group(1).strip() if blocker else "agent made no change")

        self.checkpoint(doc, step=STEP_VALIDATING, changed=changed, diffBytes=diff_bytes)
        guard = gates.check_diff(changed, diff_bytes)
        if not guard.ok:
            return self._finish(doc, "blocked", f"guard rails: {guard.detail}", gates=[guard.__dict__])

        api_dir = worktree / "apps" / "api"
        tests = [p.split("apps/api/", 1)[1] for p in changed if p.startswith("apps/api/tests/test_")]
        report = gates.standard_gates(api_dir, tests, cfg.runner)
        report.results.insert(0, guard)
        self.checkpoint(doc, gates=report.to_dict())
        if not report.ok:
            failed = "; ".join(f"{r.name}: {r.detail}" for r in report.failed())
            return self._finish(doc, "blocked", f"tests failed — {failed}"[:500])

        _git(cfg, ["add", "--", *changed], worktree)
        message = f"fix(overnight): {group.category} [{group.ats}]\n\n{agent.get('text', '')[-800:]}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
        code, out = _git(cfg, ["-c", "user.name=CareerOS overnight", "-c", "user.email=overnight@careeros.local",
                               "commit", "-q", "-m", message], worktree)
        if code != 0:
            return self._finish(doc, "blocked", f"commit failed: {out.strip()[-300:]}")
        _, commit = _git(cfg, ["rev-parse", "HEAD"], worktree)
        commit = commit.strip()
        self.checkpoint(doc, commit=commit, highRisk=gates.is_high_risk(changed))

        if gates.is_high_risk(changed):
            self.checkpoint(doc, step=STEP_REVIEW)
            review = run_review(cfg, worktree, commit, group)
            usage["reviewRuns"] += 1
            self.checkpoint(doc, review=review)
            if review["status"] != "ok":
                return self._finish(doc, "blocked", f"Codex review did not complete ({review['status']}): {review.get('errors')}")
            if review["blocking"]:
                return self._finish(doc, "blocked", "Codex review found blocking issues: " + " | ".join(review["blocking"])[:400])

        return self._finish(doc, "validated", f"validated on {branch} @ {commit[:9]}; awaiting promotion",
                            promotion="awaiting")


def run_forever(store: StateStore, cfg: ImproverConfig, pause_s: float = 120.0,
                sleep: Callable[[float], None] = time.sleep, max_cycles: int | None = None,
                after_cycle: Callable[[dict[str, Any]], None] | None = None) -> None:
    """`after_cycle` runs after every cycle (the CLI passes promotion, which
    only acts when the worker is idle and the gates pass)."""
    with store.lock("improver", "overnight improver"):
        store.event(LOOP, "start", "Improver started")
        cycles = 0
        while not store.stop_requested():
            try:
                result = Improver(store, cfg).cycle()
            except Exception as exc:
                store.event(LOOP, "error", f"Cycle failed: {exc!r}")
                result = {"skipped": "error"}
            if after_cycle is not None:
                try:
                    after_cycle(result)
                except Exception as exc:
                    store.event(LOOP, "error", f"After-cycle hook failed: {exc!r}", flag=True)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            # Idle longer when there is nothing to do, so an empty night is cheap.
            wait = pause_s * (10 if result.get("skipped") else 1)
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline and not store.stop_requested():
                sleep(min(15.0, max(0.0, deadline - time.monotonic())))
        store.event(LOOP, "stop", "Improver stopped")
