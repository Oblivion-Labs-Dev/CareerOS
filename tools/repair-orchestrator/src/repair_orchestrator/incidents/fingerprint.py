from __future__ import annotations

import hashlib
import re
from typing import Any


def _normalize_stack_location(stack_trace: str) -> str:
    if not stack_trace:
        return "unknown"
    for line in stack_trace.splitlines():
        match = re.search(r'File "([^"]+)", line (\d+)', line)
        if match:
            path = match.group(1).replace("\\", "/")
            if "site-packages" in path:
                continue
            return f"{path}:{match.group(2)}"
    return "unknown"


def compute_fingerprint(event: dict[str, Any]) -> str:
    parts = [
        str(event.get("errorType") or "UnknownError"),
        str(event.get("service") or "unknown"),
        _normalize_stack_location(str(event.get("stackTrace") or "")),
        str(event.get("endpoint") or event.get("operation") or ""),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]
