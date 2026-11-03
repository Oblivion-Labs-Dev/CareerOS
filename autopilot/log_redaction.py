"""Structured log redaction for Application Assistant."""

from __future__ import annotations

import re
from typing import Any

REDACT_PATTERNS = [
    (re.compile(r"(password|passwd|pwd)\s*[:=]\s*\S+", re.I), r"\1=***REDACTED***"),
    (re.compile(r"(token|api_key|apikey|secret|cookie|session_id)\s*[:=]\s*\S+", re.I), r"\1=***REDACTED***"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "***SSN-REDACTED***"),
    (re.compile(r"\b\d{16}\b"), "***CARD-REDACTED***"),
]

SENSITIVE_FIELD_KEYS = {
    "password", "ssn", "social_security", "credit_card", "bank_account",
    "workAuthorization", "sponsorship", "salaryExpectations",
    "raceEthnicity", "gender", "veteran", "disability", "hispanic",
}


def redact_string(text: str) -> str:
    """Redact sensitive patterns from a string."""
    result = text
    for pattern, replacement in REDACT_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def redact_dict(data: dict[str, Any], *, depth: int = 0) -> dict[str, Any]:
    """Recursively redact sensitive values from a dictionary."""
    if depth > 10:
        return {"_truncated": True}

    result: dict[str, Any] = {}
    for key, value in data.items():
        key_lower = key.lower()
        if any(sensitive.lower() in key_lower for sensitive in SENSITIVE_FIELD_KEYS):
            result[key] = "***REDACTED***"
        elif isinstance(value, str):
            result[key] = redact_string(value)
        elif isinstance(value, dict):
            result[key] = redact_dict(value, depth=depth + 1)
        elif isinstance(value, list):
            result[key] = [
                redact_dict(item, depth=depth + 1) if isinstance(item, dict)
                else redact_string(item) if isinstance(item, str)
                else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def sanitize_url(url: str) -> str:
    """Remove sensitive query parameters from URLs."""
    if "?" not in url:
        return url
    base, query = url.split("?", 1)
    sensitive_params = {"token", "session", "auth", "key", "password", "secret"}
    parts = []
    for param in query.split("&"):
        key = param.split("=")[0].lower()
        if key in sensitive_params:
            parts.append(f"{key}=***REDACTED***")
        else:
            parts.append(param)
    return f"{base}?{'&'.join(parts)}"


def create_log_entry(
    event: str,
    *,
    application_id: str = "",
    browser_run_id: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a sanitized log entry."""
    from app.db.store import now_iso

    entry: dict[str, Any] = {
        "event": event,
        "timestamp": now_iso(),
    }
    if application_id:
        entry["applicationId"] = application_id
    if browser_run_id:
        entry["browserRunId"] = browser_run_id
    if details:
        entry["details"] = redact_dict(details)
    return entry
