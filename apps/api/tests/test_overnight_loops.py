"""Overnight loops: dispatcher, recovery, grouping, promotion and requeue.

Everything runs against fakes (a scripted API, a fake coding agent and fake
gate commands). Git is real (a throwaway repository), because the improver's
worktree handling and promotion's fast-forward are the runtime behaviour that
matters. No model, no browser, no live API is reached.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.overnight import api_client, gates, promotion, report, supervisor
from app.services.overnight.api_client import ApiError
from app.services.overnight.grouping import KIND_USER_INPUT, build_groups, next_fixable, requeue_candidates
from app.services.overnight.improver import Improver, ImproverConfig
from app.services.overnight.state import LockHeld, StateStore

NOW = datetime(2026, 10, 31, 3, 0, tzinfo=timezone.utc)
SIG = "Unhandled automation exception|greenhouse"


class FakeApi:
    def __init__(self, status=None, reprocess=None, down=False):
        self.status = status if status is not None else {}
        self.reprocess = reprocess or {}
        self.down = down
        self.posts: list[tuple[str, dict | None]] = []

    def get(self, path):
        if self.down:
            raise ApiError(f"GET {path} unreachable")
        assert path == "/autopilot/status"
        return self.status

    def post(self, path, body=None):
        if self.down:
            raise ApiError(f"POST {path} unreachable")
        self.posts.append((path, body))
        if path.endswith("/reprocess"):
            job_id = path.split("/")[-2]
            return self.reprocess.get(job_id, {"success": True, "id": job_id})
        return {"status": "RUNNING"}


def job(i, status="FAILED", error="Unhandled exception: KeyError foo", **extra):
    return {"id": str(i), "status": status, "lastError": error,
            "applicationUrl": f"https://boards.greenhouse.io/acme/jobs/{i}", **extra}


@pytest.fixture
def store(tmp_path):
    return StateStore(tmp_path / "state")


# ---- Loop A: decide ---------------------------------------------------------
def run(status, **extra):
    return {"status": status, "run": {"id": "r1", "status": status, **extra.pop("run", {})}, **extra}


@pytest.mark.parametrize("obs, action, flag", [
    ({"apiError": "refused"}, supervisor.WAIT, False),
    ({**run("RUNNING"), "apiProcesses": 2}, supervisor.HOLD, True),
    ({**run("RUNNING"), "concurrency": 2}, supervisor.HOLD, True),
    ({**run("RUNNING"), "workers": [{"status": "applying"}]}, supervisor.NOTHING, False),
    (run("RUNNING", run={"lastHeartbeatAt": (NOW - timedelta(minutes=2)).isoformat()}), supervisor.NOTHING, False),
    (run("RUNNING", run={"lastHeartbeatAt": (NOW - timedelta(minutes=40)).isoformat()}), supervisor.RESUME, False),
    ({**run("PAUSED"), "queueSize": 5, "recentLogs": [{"timestamp": "1", "message": "Queue empty and no new postings"}]},
     supervisor.RESUME, False),
    ({**run("PAUSED"), "queueSize": 5, "recentLogs": [{"timestamp": "1", "message": "Autopilot run paused by you"}]},
     supervisor.HOLD, False),
    ({**run("PAUSED"), "recentLogs": [{"timestamp": "1", "message": "something new"}]}, supervisor.HOLD, True),
    ({"status": "STOPPED", "run": None, "queueSize": 3}, supervisor.HOLD, False),
])
def test_decide(obs, action, flag):
    d = supervisor.decide(obs, {}, supervisor.Policy(), NOW)
    assert (d.action, d.flag) == (action, flag), d.reason


def test_decide_never_resumes_a_live_application_even_when_heartbeat_is_stale():
    obs = run("RUNNING", run={"lastHeartbeatAt": (NOW - timedelta(hours=3)).isoformat()},
              workers=[{"status": "submitting"}])
    assert supervisor.decide(obs, {}, supervisor.Policy(), NOW).action == supervisor.NOTHING


def test_decide_infra_budget_and_queue_budget_hold():
    infra = {**run("PAUSED"), "recentLogs": [{"timestamp": "1", "message": "Fatal worker infrastructure error: x"}]}
    assert supervisor.decide(infra, {"infraResumes": 3}, supervisor.Policy(), NOW).action == supervisor.HOLD
    recent = {"infraResumes": 1, "lastInfraResumeAt": (NOW - timedelta(minutes=5)).isoformat()}
    assert supervisor.decide(infra, recent, supervisor.Policy(), NOW).action == supervisor.WAIT
    empty = {**run("PAUSED"), "queueSize": 4, "recentLogs": [{"timestamp": "1", "message": "Queue empty and no new postings"}]}
    assert supervisor.decide(empty, {"queueResumes": 8}, supervisor.Policy(), NOW).flag


# ---- Loop A: run_cycle ------------------------------------------------------
def test_cycle_resumes_once_through_the_api(store):
    api = FakeApi({**run("PAUSED"), "queueSize": 2,
                   "recentLogs": [{"timestamp": "1", "message": "Queue empty and no new postings"}]})
    mem = supervisor.run_cycle(store, api, supervisor.Policy(), jobs_reader=lambda: [job(1)],
                               processes=lambda: 1, now=NOW)
    assert api.posts == [("/autopilot/start", {})]
    assert mem["queueResumes"] == 1 and mem["nextCheckAt"] == (NOW + timedelta(minutes=30)).isoformat(timespec="seconds")
    assert store.read("supervisor.json")["lastDecision"]["action"] == supervisor.RESUME


def test_cycle_leaves_a_busy_worker_alone_and_records_refusals(store):
    busy = FakeApi({**run("RUNNING"), "workers": [{"status": "applying"}]})
    supervisor.run_cycle(store, busy, supervisor.Policy(), jobs_reader=None, processes=lambda: 1, now=NOW)
    assert busy.posts == []

    class Refusing(FakeApi):
        def post(self, path, body=None):
            raise ApiError("409", 409, {"detail": "live-apply gate closed"})

    refusing = Refusing({**run("RUNNING", run={"lastHeartbeatAt": "2026-10-30T00:00:00+00:00"})})
    mem = supervisor.run_cycle(store, refusing, supervisor.Policy(), jobs_reader=None, processes=lambda: 1, now=NOW)
    assert mem["lastDecision"]["result"] == "refused" and mem["lastDecision"]["flag"]


def test_cycle_api_down_counts_and_flags(store):
    api = FakeApi(down=True)
    for _ in range(2):
        mem = supervisor.run_cycle(store, api, supervisor.Policy(), jobs_reader=None, processes=lambda: 0, now=NOW)
    assert mem["apiDownCycles"] == 2 and mem["lastDecision"]["flag"]


# ---- grouping ---------------------------------------------------------------
def test_grouping_counts_only_eligible_and_ranks_by_size():
    jobs = [job(i) for i in range(1, 6)]
    jobs += [job(10, error="Navigation timeout of 30000 ms exceeded")]
    jobs += [job(20, status="SUBMITTED"), {**job(21), "applicationUrl": job(20)["applicationUrl"]}]  # duplicate
    jobs += [job(30, status="SUBMISSION_UNKNOWN"), job(31, pendingQuestions=[{"q": "Visa?"}])]
    groups = build_groups(jobs)
    top = next_fixable(groups)
    assert top.signature == SIG and top.eligible == 5
    assert top.excluded.get("duplicate") == 1
    assert any(g.kind == KIND_USER_INPUT for g in groups)
    assert "30" not in {i for g in groups for i in g.eligible_ids}


def test_candidate_account_reviews_are_not_code_fixable():
    msg = ("Staged for human review: This employer's apply flow requires a candidate account "
           "(the form asks for a password)")
    jobs = [job(i, status="MANUAL_REVIEW", error=msg) for i in range(1, 6)]
    assert next_fixable(build_groups(jobs)) is None


def test_blocked_history_skips_a_group():
    jobs = [job(i) for i in range(1, 4)]
    assert next_fixable(build_groups(jobs, {SIG: {"attempts": 2}})) is None
    assert next_fixable(build_groups(jobs, {SIG: {"blocked": True}})) is None


def test_requeue_candidates_rederive_and_exclude():
    jobs = [job(1), job(2, status="QUEUED"), job(3, pendingQuestions=[{"q": "x"}]), job(4, status="SUBMITTED"),
            {**job(5), "applicationUrl": job(4)["applicationUrl"]}]
    assert [j["id"] for j in requeue_candidates(jobs, SIG)] == ["1"]


# ---- gates ------------------------------------------------------------------
def test_check_diff_guard_rails():
    assert gates.check_diff(["apps/api/app/x.py", "apps/api/tests/test_x.py"], 100).ok
    assert "no regression test" in gates.check_diff(["apps/api/app/x.py"], 100).detail
    for protected in (".env", "apps/api/app/services/overnight/gates.py", "apps/api/tests/conftest.py",
                      "apps/api/tests/test_overnight_loops.py", ".github/workflows/ci.yml"):
        assert not gates.check_diff([protected, "apps/api/tests/test_y.py"], 10).ok, protected
    assert not gates.check_diff([f"apps/api/tests/test_{i}.py" for i in range(25)], 10).ok
    assert gates.is_high_risk(["apps/api/app/services/application_assistant/autopilot_runner.py"])
    assert not gates.is_high_risk(["apps/api/app/services/field_fill.py"])


# ---- Loop B: improver with real git, fake agent, fake gates -----------------
def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "apps/api/app").mkdir(parents=True)
    (root / "apps/api/tests").mkdir(parents=True)
    (root / "apps/api/app/mod.py").write_text("VALUE = 1\n")
    _git(tmp_path, "init", "-q", "-b", "prod-readiness", str(root))
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    return root


class FakeRunner:
    """Real git; scripted agent, review and gate commands. Records every call."""

    def __init__(self, agent_files=None, tests_pass=True, review="ok", blocking=""):
        self.agent_files = agent_files if agent_files is not None else {
            "apps/api/app/mod.py": "VALUE = 2\n", "apps/api/tests/test_mod.py": "def test_v():\n    pass\n"}
        self.tests_pass = tests_pass
        self.review = review
        self.blocking = blocking
        self.calls: list[list[str]] = []

    def __call__(self, cmd, cwd, timeout):
        self.calls.append(list(cmd))
        if cmd[0] == "git":
            return gates.subprocess_runner(["git", "-c", "user.name=t", "-c", "user.email=t@t", *cmd[1:]], cwd, timeout)
        if cmd[0] == "claude":
            for rel, text in self.agent_files.items():
                (Path(cwd) / rel).parent.mkdir(parents=True, exist_ok=True)
                (Path(cwd) / rel).write_text(text)
            return 0, json.dumps({"result": "Fixed the KeyError.", "is_error": False, "total_cost_usd": 0.0})
        if cmd[0] == "codex-bridge":
            return 0, json.dumps({"status": self.review, "lastMessage": self.blocking})
        if cmd[:3] == [sys.executable, "-m", "compileall"]:
            return 0, ""
        if cmd[:3] == [sys.executable, "-m", "pytest"]:
            return (0, "5 passed") if self.tests_pass else (1, "1 failed")
        raise AssertionError(f"unexpected command {cmd}")


def _gate_files(root):
    # run_pytest only runs files that exist in the worktree.
    for rel in (*gates.SUBMISSION_GUARD_TESTS, *gates.SECURITY_GATE_TESTS, *gates.OVERNIGHT_TESTS):
        p = root / "apps/api" / rel
        p.write_text("def test_ok():\n    pass\n")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "gate tests")


def _cfg(repo, tmp_path, runner, jobs=None):
    return ImproverConfig(repo_root=repo, worktrees_dir=tmp_path / "wt", min_free_ram_mb=0,
                          jobs_reader=lambda: jobs if jobs is not None else [job(i) for i in range(1, 5)],
                          runner=runner, evolution_lock=tmp_path / "engine.lock")


def test_improver_validates_one_fix_and_keeps_its_branch(store, repo, tmp_path):
    _gate_files(repo)
    runner = FakeRunner()
    item = Improver(store, _cfg(repo, tmp_path, runner)).cycle()
    assert item["step"] == "validated", item["detail"]
    assert item["signature"] == SIG and Path(item["worktree"]).exists()
    assert _git(repo, "show", f"{item['commit']}:apps/api/app/mod.py") == "VALUE = 2"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "prod-readiness"  # target untouched
    assert _git(repo, "rev-parse", "HEAD") != item["commit"]
    assert not any(c[0] == "codex-bridge" for c in runner.calls)  # not high risk
    assert not (tmp_path / "engine.lock").exists()
    # the same group is not picked again
    assert Improver(store, _cfg(repo, tmp_path, runner)).cycle() == {"skipped": "no fixable group"}


def test_improver_reverts_when_tests_fail(store, repo, tmp_path):
    _gate_files(repo)
    item = Improver(store, _cfg(repo, tmp_path, FakeRunner(tests_pass=False))).cycle()
    assert item["step"] == "blocked" and "tests failed" in item["detail"]
    assert not (tmp_path / "wt").exists() or not any((tmp_path / "wt").iterdir())
    assert item["branch"] not in _git(repo, "branch", "--list")


def test_improver_blocks_protected_paths_and_high_risk_needs_review(store, repo, tmp_path):
    _gate_files(repo)
    bad = FakeRunner(agent_files={"apps/api/app/services/overnight/gates.py": "x = 1\n",
                                  "apps/api/tests/test_a.py": "def test_a():\n    pass\n"})
    assert "protected path" in Improver(store, _cfg(repo, tmp_path, bad)).cycle()["detail"]

    risky = FakeRunner(agent_files={"apps/api/app/autopilot_runner.py": "x = 1\n",
                                    "apps/api/tests/test_b.py": "def test_b():\n    pass\n"},
                       blocking="BLOCKING: double submit on retry")
    other = [job(i, error="Navigation timeout of 30000 ms exceeded") for i in range(1, 4)]
    item = Improver(store, _cfg(repo, tmp_path, risky, jobs=other)).cycle()
    assert item["step"] == "blocked" and "double submit" in item["detail"]


def test_improver_recovers_an_interrupted_attempt(store, repo, tmp_path):
    wt = tmp_path / "wt" / "half"
    _git(repo, "worktree", "add", "-q", "-b", "overnight/fix-half", str(wt))
    store.write("improver.json", {"current": {"step": "agent", "signature": SIG, "branch": "overnight/fix-half",
                                              "worktree": str(wt)}})
    item = Improver(store, _cfg(repo, tmp_path, FakeRunner())).recover()
    assert item["step"] == "blocked" and "interrupted" in item["detail"]
    assert not wt.exists() and "overnight/fix-half" not in _git(repo, "branch", "--list")
    assert store.read("improver.json")["current"] is None


def test_improver_waits_while_another_lane_holds_the_evolution_lock(store, repo, tmp_path):
    cfg = _cfg(repo, tmp_path, FakeRunner())
    from app.services.overnight.state import acquire_file_lock
    acquire_file_lock(cfg.evolution_lock, "nightly evolution")
    try:
        assert "held by nightly evolution" in Improver(store, cfg).cycle()["skipped"]
    finally:
        cfg.evolution_lock.unlink()


# ---- promotion --------------------------------------------------------------
def _validated(store, repo, tmp_path):
    _gate_files(repo)
    item = Improver(store, _cfg(repo, tmp_path, FakeRunner())).cycle()
    assert item["step"] == "validated"
    return item


def _pcfg(repo, tmp_path, runner=None):
    return promotion.PromotionConfig(target_repo=repo, worktrees_dir=tmp_path / "wt", runner=runner or FakeRunner())


IDLE = {"status": "PAUSED", "run": {"id": "r"}, "workers": [{"status": "idle"}]}


def test_promotion_waits_for_an_idle_worker(store, repo, tmp_path):
    item = _validated(store, repo, tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    for status in ({"status": "RUNNING"}, {"status": "PAUSED", "activeJob": {"id": "9"}},
                   {"status": "PAUSED", "workers": [{"status": "applying"}]}):
        out = promotion.promote_ready(store, _pcfg(repo, tmp_path), FakeApi(status), lambda: 1)
        assert "worker busy" in out[0]["skipped"]
    out = promotion.promote_ready(store, _pcfg(repo, tmp_path), FakeApi(down=True), lambda: 1)
    assert "not promoting blind" in out[0]["skipped"]
    assert _git(repo, "rev-parse", "HEAD") == head and promotion.state(store)["fixes"] == {}
    assert promotion.awaiting(store)[0]["branch"] == item["branch"]


def test_promotion_refuses_main_and_dirty_targets(store, repo, tmp_path):
    _validated(store, repo, tmp_path)
    _git(repo, "checkout", "-q", "-b", "main")
    out = promotion.promote_ready(store, _pcfg(repo, tmp_path), FakeApi(IDLE), lambda: 1)
    assert "never writes to it" in out[0]["skipped"]
    _git(repo, "checkout", "-q", "prod-readiness")
    (repo / "apps/api/app/mod.py").write_text("VALUE = 99\n")
    out = promotion.promote_ready(store, _pcfg(repo, tmp_path), FakeApi(IDLE), lambda: 1)
    assert "uncommitted" in out[0]["skipped"]
    assert (repo / "apps/api/app/mod.py").read_text() == "VALUE = 99\n"


def test_promotion_rejects_when_integration_gates_fail(store, repo, tmp_path):
    _validated(store, repo, tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    out = promotion.promote_ready(store, _pcfg(repo, tmp_path, FakeRunner(tests_pass=False)), FakeApi(IDLE), lambda: 1)
    assert out[0]["status"] == "rejected" and _git(repo, "rev-parse", "HEAD") == head
    assert promotion.awaiting(store) == []  # recorded, not retried every cycle


def test_promotion_fast_forwards_and_is_not_live(store, repo, tmp_path):
    item = _validated(store, repo, tmp_path)
    out = promotion.promote_ready(store, _pcfg(repo, tmp_path), FakeApi(IDLE), lambda: 1)
    assert out[0]["status"] == "promoted" and out[0]["liveAt"] is None
    assert (repo / "apps/api/app/mod.py").read_text().strip() == "VALUE = 2"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "prod-readiness"
    assert "overnight-integrate" not in _git(repo, "worktree", "list")
    # nothing is requeued before a person marks it live
    api = FakeApi(IDLE)
    assert promotion.requeue_ready(store, api, lambda: [job(1)])["requeued"] == 0 and api.posts == []
    assert promotion.mark_live(store, item["branch"])["liveAt"]


def test_requeue_once_per_job_through_the_reprocess_route(store):
    store.write("improver.json", {"fixes": [{"step": "validated", "branch": "b1", "commit": "c", "signature": SIG}]})
    promotion.mark_live(store, "b1", "merged + restarted")
    jobs = [job(1), job(2), job(3), job(4, status="SUBMITTED")]
    api = FakeApi(reprocess={"2": {"success": False, "message": "Refusing: may already be submitted"}})
    out = promotion.requeue_ready(store, api, lambda: jobs, cap=25)
    assert out["requeued"] == 2
    assert sorted(p for p, _ in api.posts) == [f"/autopilot/jobs/{i}/reprocess" for i in (1, 2, 3)]
    book = store.read("requeue.json")["fixes"]["b1"]
    assert sorted(book["requeued"]) == ["1", "3"] and "2" in book["refused"]
    # same jobs failing again are not requeued a second time
    api2 = FakeApi()
    assert promotion.requeue_ready(store, api2, lambda: jobs)["requeued"] == 0 and api2.posts == []


def test_requeue_cap_and_api_down(store):
    store.write("improver.json", {"fixes": [{"step": "validated", "branch": "b1", "commit": "c", "signature": SIG}]})
    promotion.mark_live(store, "b1")
    jobs = [job(i) for i in range(1, 11)]
    api = FakeApi()
    assert promotion.requeue_ready(store, api, lambda: jobs, cap=3)["requeued"] == 3
    out = promotion.requeue_ready(store, FakeApi(down=True), lambda: jobs, cap=3)
    assert out["requeued"] == 0 and "unreachable" in out["error"]
    assert len(store.read("requeue.json")["fixes"]["b1"]["requeued"]) == 3


def test_supervisor_cycle_requeues_live_fixes(store):
    store.write("improver.json", {"fixes": [{"step": "validated", "branch": "b1", "commit": "c", "signature": SIG}]})
    promotion.mark_live(store, "b1")
    api = FakeApi({"status": "PAUSED", "run": {"id": "r"}, "workers": [],
                   "recentLogs": [{"timestamp": "1", "message": "Autopilot run paused by you"}]})
    mem = supervisor.run_cycle(store, api, supervisor.Policy(), jobs_reader=lambda: [job(1)], processes=lambda: 1, now=NOW)
    assert mem["lastDecision"]["requeue"]["requeued"] == 1
    assert ("/autopilot/start", {}) not in api.posts  # user pause is respected


# ---- state, processes, report -----------------------------------------------
def test_loop_lock_is_exclusive(store):
    with store.lock("supervisor", "one"):
        with pytest.raises(LockHeld):
            with store.lock("supervisor", "two"):
                pass
    with store.lock("supervisor", "three"):
        pass


def test_run_forever_honours_the_stop_flag(store):
    api = FakeApi({"status": "PAUSED", "run": {"id": "r"},
                   "recentLogs": [{"timestamp": "1", "message": "Autopilot run paused by you"}]})
    seen = []

    def sleep(_s):
        store.request_stop()

    supervisor.run_forever(store, api, supervisor.Policy(), sleep=sleep, jobs_reader=None,
                           after_cycle=seen.append)
    assert len(seen) == 1 and store.lock_holder("supervisor") is None


def test_api_server_processes_drops_launcher_wrappers(monkeypatch):
    class P:
        def __init__(self, pid, ppid, cmd, cwd="C:/api"):
            self.info = {"pid": pid, "ppid": ppid, "cmdline": cmd, "cwd": cwd}

    uv = ["python", "-m", "uvicorn", "app.main:app", "--port", "4000"]
    procs = [P(10, 1, ["cmd.exe", "/c", *uv]), P(11, 10, uv), P(20, 1, [*uv, "--reload"], "C:/dev"),
             P(30, 1, ["python", "other.py"])]
    import psutil

    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter(procs))
    servers = api_client.api_server_processes()
    assert sorted(s["pid"] for s in servers) == [10, 20]
    monkeypatch.setattr(api_client, "api_server_processes", lambda: servers)
    assert supervisor.count_api_processes() == 1
    assert api_client.live_api_dir() is None  # two distinct dirs: ambiguous, so no guess


def test_report_shows_unknown_without_a_db_and_counts_with_one(store):
    store.write("session.json", {"startedAt": "2026-10-31T00:00:00+00:00"})
    data = report.collect(store, None)
    assert data["metrics"]["verifiedSubmissions"] is None
    assert "Verified submissions: unknown" in report.render_markdown(data)

    jobs = [job(1, status="SUBMITTED", submittedAt="2026-10-31T02:00:00+00:00",
                applicationStartedAt="2026-10-31T01:50:00+00:00"),
            job(2, status="SUBMITTED", submittedAt="2026-10-30T02:00:00+00:00"),
            job(3, status="SUBMISSION_UNKNOWN", updatedAt="2026-10-31T02:00:00+00:00")]
    out = report.write_outputs(store, lambda: jobs)
    md = Path(out["report"]).read_text(encoding="utf-8")
    assert "Verified submissions: 1" in md and "Applications attempted: 1" in md
    assert "SUBMISSION_UNKNOWN" in md
    assert "<title>CareerOS overnight</title>" in Path(out["dashboard"]).read_text(encoding="utf-8")
