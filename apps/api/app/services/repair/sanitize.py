from __future__ import annotations

import re
import uuid

SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|secret|token|authorization|cookie|api[_-]?key|resume|profile|ssn|email_body)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]


def sanitize_string(value: str, *, max_length: int = 2000) -> str:
    cleaned = value
    for pattern in SENSITIVE_VALUE_PATTERNS:
        cleaned = pattern.sub("[REDACTED]", cleaned)
    if len(cleaned) > max_length:
        return cleaned[: max_length - 3] + "..."
    return cleaned


def sanitize_metadata(metadata: dict | None) -> dict:
    if not metadata:
        return {}
    sanitized: dict = {}
    for key, value in metadata.items():
        if SENSITIVE_KEY_PATTERN.search(str(key)):
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, str):
            sanitized[key] = sanitize_string(value, max_length=500)
        else:
            sanitized[key] = value
    return sanitized


def sanitize_log_entry(entry: dict) -> dict:
    return {
        **entry,
        "message": sanitize_string(str(entry.get("message") or "")),
        "stack_trace": sanitize_string(str(entry.get("stack_trace") or ""), max_length=8000),
        "metadata": sanitize_metadata(entry.get("metadata") or {}),
    }
