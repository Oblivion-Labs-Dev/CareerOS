from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|secret|token|authorization|cookie|api[_-]?key|resume|profile|ssn|email_body)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]+-----"),
]


def sanitize_string(value: str, *, max_length: int = 2000) -> str:
    cleaned = value
    for pattern in SENSITIVE_VALUE_PATTERNS:
        cleaned = pattern.sub("[REDACTED]", cleaned)
    if len(cleaned) > max_length:
        return cleaned[: max_length - 3] + "..."
    return cleaned


def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        if SENSITIVE_KEY_PATTERN.search(str(key)):
            sanitized[key] = "[REDACTED]"
            continue
        if isinstance(value, str):
            sanitized[key] = sanitize_string(value, max_length=500)
        elif isinstance(value, dict):
            sanitized[key] = sanitize_metadata(value)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_string(item, max_length=500) if isinstance(item, str) else item for item in value[:20]
            ]
        else:
            sanitized[key] = value
    return sanitized


def sanitize_error_event(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload)
    sanitized["message"] = sanitize_string(str(payload.get("message") or ""))
    sanitized["stackTrace"] = sanitize_string(str(payload.get("stackTrace") or ""), max_length=8000)
    sanitized["metadata"] = sanitize_metadata(payload.get("metadata") or {})
    return sanitized
