"""Structured Failure Taxonomy and Context Builder for CareerOS Application Automation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FailureType(str, Enum):
    NAVIGATION_TIMEOUT = "NAVIGATION_TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
    SELECTOR_CHANGED = "SELECTOR_CHANGED"
    PAGE_STRUCTURE_CHANGED = "PAGE_STRUCTURE_CHANGED"
    BROWSER_CRASH = "BROWSER_CRASH"
    AI_TIMEOUT = "AI_TIMEOUT"
    AI_INVALID_RESPONSE = "AI_INVALID_RESPONSE"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"
    UPLOAD_ERROR = "UPLOAD_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CAPTCHA = "CAPTCHA"
    UNSUPPORTED_QUESTION = "UNSUPPORTED_QUESTION"
    UNSUPPORTED_ATS = "UNSUPPORTED_ATS"
    JOB_CLOSED = "JOB_CLOSED"
    DUPLICATE_APPLICATION = "DUPLICATE_APPLICATION"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    CODE_ERROR = "CODE_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass
class FailureContext:
    failure_id: str
    job_id: str
    run_id: str
    application_url: str
    failure_type: FailureType
    error_message: str
    ats_type: str = "custom"
    adapter_name: str = "GenericAdapter"
    adapter_version: str = "1.0.0"
    current_step: str = "INITIAL"
    previous_checkpoint: str = ""
    stack_trace: str = ""
    screenshot_path: str = ""
    dom_snapshot_path: str = ""
    html_snapshot_path: str = ""
    browser_console_logs: list[str] = field(default_factory=list)
    network_errors: list[str] = field(default_factory=list)
    selector_attempts: list[str] = field(default_factory=list)
    generated_answers: dict[str, Any] = field(default_factory=dict)
    last_successful_action: str = ""
    running_commit: str = "main"

    def to_dict(self) -> dict[str, Any]:
        return {
            "failureId": self.failure_id,
            "jobId": self.job_id,
            "runId": self.run_id,
            "atsType": self.ats_type,
            "adapterName": self.adapter_name,
            "adapterVersion": self.adapter_version,
            "applicationUrl": self.application_url,
            "failureType": self.failure_type.value if isinstance(self.failure_type, FailureType) else str(self.failure_type),
            "errorMessage": self.error_message,
            "stackTrace": self.stack_trace,
            "currentStep": self.current_step,
            "previousCheckpoint": self.previous_checkpoint,
            "screenshotPath": self.screenshot_path,
            "domSnapshotPath": self.dom_snapshot_path,
            "htmlSnapshotPath": self.html_snapshot_path,
            "browserConsoleLogs": self.browser_console_logs,
            "networkErrors": self.network_errors,
            "selectorAttempts": self.selector_attempts,
            "generatedAnswers": self.generated_answers,
            "lastSuccessfulAction": self.last_successful_action,
            "runningCommit": self.running_commit,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailureContext:
        ft_val = data.get("failureType", FailureType.UNKNOWN_ERROR.value)
        try:
            ft = FailureType(ft_val)
        except ValueError:
            ft = FailureType.UNKNOWN_ERROR

        return cls(
            failure_id=data.get("failureId", ""),
            job_id=data.get("jobId", ""),
            run_id=data.get("runId", ""),
            application_url=data.get("applicationUrl", ""),
            failure_type=ft,
            error_message=data.get("errorMessage", ""),
            ats_type=data.get("atsType", "custom"),
            adapter_name=data.get("adapterName", "GenericAdapter"),
            adapter_version=data.get("adapterVersion", "1.0.0"),
            current_step=data.get("currentStep", "INITIAL"),
            previous_checkpoint=data.get("previousCheckpoint", ""),
            stack_trace=data.get("stackTrace", ""),
            screenshot_path=data.get("screenshotPath", ""),
            dom_snapshot_path=data.get("domSnapshotPath", ""),
            html_snapshot_path=data.get("htmlSnapshotPath", ""),
            browser_console_logs=data.get("browserConsoleLogs") or [],
            network_errors=data.get("networkErrors") or [],
            selector_attempts=data.get("selectorAttempts") or [],
            generated_answers=data.get("generatedAnswers") or {},
            last_successful_action=data.get("lastSuccessfulAction", ""),
            running_commit=data.get("runningCommit", "main"),
        )


def create_failure_signature(failure: FailureContext) -> str:
    """Generate a stable, normalized signature for failure deduplication and knowledge base matching."""
    norm_msg = re.sub(r"0x[0-9a-fA-F]+", "[HEX]", failure.error_message)
    norm_msg = re.sub(r"\d+", "[NUM]", norm_msg).strip().lower()

    raw_str = "|".join([
        str(failure.ats_type).lower(),
        str(failure.adapter_name).lower(),
        str(failure.failure_type.value).lower(),
        str(failure.current_step).lower(),
        norm_msg[:150],
        ":".join(failure.selector_attempts[:3]),
    ])
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]
