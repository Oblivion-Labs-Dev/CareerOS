from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ReadLogOptions:
    limit: int = 500
    include_client_logs: bool = True
    include_open_errors: bool = True
    include_error_history: bool = True


@dataclass
class LogEntry:
    id: str
    level: str
    source: str
    message: str
    timestamp: str
    signature: str = ""
    endpoint: str = ""
    stack_trace: str = ""
    status_code: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentWorkspace:
    repo_root: str
    worktrees_dir: str


@dataclass
class AgentRun:
    run_id: str
    task_id: str
    branch: str
    worktree_path: str
    status: str = "pending"
    changed_files: list[str] = field(default_factory=list)
    diff_summary: str = ""
    commands_run: list[str] = field(default_factory=list)
    output: str = ""


@dataclass
class RepairTask:
    task_id: str
    fingerprint: str
    title: str
    status: str
    severity: str
    component: str
    exception_message: str
    stack_trace: str
    relevant_logs: list[str] = field(default_factory=list)
    occurrence_count: int = 1
    first_occurrence: str = ""
    last_occurrence: str = ""
    endpoint: str = ""
    service: str = "career-os-api"
    application_version: str = "0.1.0"
    git_commit_sha: str = ""
    suspected_source_files: list[str] = field(default_factory=list)
    reproduction: str = ""
    validation_commands: list[str] = field(default_factory=list)
    agent_branch: str = ""
    agent_worktree: str = ""
    patch_summary: str = ""
    validation: dict[str, Any] | None = None
    agent_run: dict[str, Any] | None = None


class LogSource(Protocol):
    def read_recent_logs(self, options: ReadLogOptions) -> list[LogEntry]:
        ...


class CodingAgentAdapter(Protocol):
    def start(self, task: RepairTask, workspace: AgentWorkspace) -> AgentRun:
        ...

    def get_status(self, run_id: str) -> dict[str, Any]:
        ...

    def cancel(self, run_id: str) -> None:
        ...
