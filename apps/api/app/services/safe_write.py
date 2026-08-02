"""Atomic file writes with optional backup (career-ops safe-write pattern)."""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path


def atomic_write(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    backup: bool = True,
) -> Path | None:
    """Write content atomically via temp file + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    if backup and path.is_file():
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = path.with_suffix(path.suffix + f".bak-{timestamp}-{os.getpid()}-{uuid.uuid4().hex[:8]}")
        shutil.copy2(path, backup_path)

    temp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(content, encoding=encoding)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
    return backup_path
