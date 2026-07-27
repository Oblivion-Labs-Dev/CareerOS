from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


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
    metadata: dict[str, Any] = field(default_factory=dict)


class CodingAgentAdapter(ABC):
    @abstractmethod
    async def start(self, task: dict[str, Any], workspace: AgentWorkspace) -> AgentRun:
        raise NotImplementedError

    @abstractmethod
    async def get_status(self, run_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def cancel(self, run_id: str) -> None:
        raise NotImplementedError
