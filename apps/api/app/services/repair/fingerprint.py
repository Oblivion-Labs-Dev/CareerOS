from __future__ import annotations

import hashlib
import re


def normalize_stack_location(stack_trace: str) -> str:
    if not stack_trace:
        return "unknown"
    for line in stack_trace.splitlines():
        match = re.search(r'File "([^"]+)", line (\d+)', line)
        if match:
            path = match.group(1).replace("\\", "/")
            if "site-packages" not in path:
                return f"{path}:{match.group(2)}"
    return "unknown"


def compute_fingerprint(*, error_type: str, service: str, signature: str, endpoint: str, stack_trace: str = "") -> str:
    parts = [
        error_type or "UnknownError",
        service or "career-os-api",
        signature or endpoint or normalize_stack_location(stack_trace),
        endpoint or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
