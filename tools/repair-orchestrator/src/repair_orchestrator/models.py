from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStatus(str, Enum):
    DETECTED = "detected"
    TRIAGED = "triaged"
    READY_FOR_AGENT = "ready_for_agent"
    IMPLEMENTING = "implementing"
    VALIDATING = "validating"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    READY_FOR_HUMAN = "ready_for_human"
    CLOSED = "closed"
    FAILED = "failed"


Severity = Literal["debug", "info", "warning", "error", "critical"]
ReviewDecision = Literal["approve", "reject", "needs_changes", "human_review"]
RiskLevel = Literal["low", "medium", "high", "critical"]


class StructuredErrorEvent(BaseModel):
    timestamp: str = Field(default_factory=utc_now_iso)
    severity: Severity = "error"
    service: str
    environment: str = "local"
    errorType: str
    message: str
    stackTrace: str = ""
    correlationId: str = ""
    endpoint: str = ""
    gitCommitSha: str = ""
    applicationVersion: str = "0.1.0"
    sourceLocation: str = ""
    feature: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    causedBy: str | None = None


class ReviewResult(BaseModel):
    decision: ReviewDecision
    confidence: float = Field(ge=0, le=1)
    summary: str
    findings: list[str] = Field(default_factory=list)
    requiredActions: list[str] = Field(default_factory=list)
    riskLevel: RiskLevel = "low"


class AgentRunStatus(BaseModel):
    runId: str
    taskId: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    branch: str = ""
    worktreePath: str = ""
    changedFiles: list[str] = Field(default_factory=list)
    diffSummary: str = ""
    commandsRun: list[str] = Field(default_factory=list)
    output: str = ""
    startedAt: str = ""
    finishedAt: str | None = None
    error: str | None = None


class ValidationResult(BaseModel):
    passed: bool
    commands: list[dict[str, Any]] = Field(default_factory=list)
    regressionTestPresent: bool = False
    completedAt: str = Field(default_factory=utc_now_iso)


class RepairTaskView(BaseModel):
    taskId: str
    incidentFingerprint: str
    title: str
    status: TaskStatus
    severity: Severity
    component: str
    exceptionMessage: str
    stackTrace: str
    relevantLogs: list[str] = Field(default_factory=list)
    occurrenceCount: int
    firstOccurrence: str
    lastOccurrence: str
    gitCommitSha: str = ""
    applicationVersion: str = ""
    suspectedSourceFiles: list[str] = Field(default_factory=list)
    reproduction: str = ""
    validationCommands: list[str] = Field(default_factory=list)
    agentBranch: str = ""
    agentWorktree: str = ""
    patchSummary: str = ""
    validation: ValidationResult | None = None
    review: ReviewResult | None = None
    prTitle: str = ""
    prBody: str = ""
    auditHistory: list[dict[str, Any]] = Field(default_factory=list)
