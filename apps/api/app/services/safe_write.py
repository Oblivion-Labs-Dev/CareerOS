"""Atomic file writes with optional backup (career-ops safe-write pattern)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path


def atomic_write(path: Path, content: str, *, encoding: str = "utf-8", backup: bool = True) -> None:
    """Write content atomically via temp file + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.is_file():
        backup_path = path.with_suffix(path.suffix + f".bak-{os.getpid()}")
        backup_path.write_text(path.read_text(encoding=encoding), encoding=encoding)

    temp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(content, encoding=encoding)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
