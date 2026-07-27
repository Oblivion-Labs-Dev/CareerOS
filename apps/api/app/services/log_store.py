import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.error_fix_tracker import error_fix_tracker

MAX_LOG_LINES = 500
LOG_DIR = Path(__file__).resolve().parents[2] / "data" / "logs"
LOG_FILE = LOG_DIR / "client.jsonl"
_memory_logs: deque[dict[str, Any]] = deque(maxlen=MAX_LOG_LINES)


def append_client_log(entry: dict[str, Any]) -> dict[str, Any]:
    record = {"ts": datetime.now(timezone.utc).isoformat(), "level": "info", **entry}
    _memory_logs.appendleft(record)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    trim_log_file()
    error_fix_tracker.record_client_log(record)
    return record


def read_client_logs(limit: int = 100) -> list[dict[str, Any]]:
    if LOG_FILE.is_file():
        lines = [line for line in LOG_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
        parsed: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                parsed.append({"ts": "", "level": "warn", "source": "server", "message": line})
        parsed.reverse()
        return parsed
    return list(_memory_logs)[:limit]


def clear_client_logs() -> None:
    _memory_logs.clear()
    if LOG_FILE.is_file():
        LOG_FILE.unlink()


def trim_log_file() -> None:
    if not LOG_FILE.is_file():
        return
    lines = [line for line in LOG_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) <= MAX_LOG_LINES:
        return
    LOG_FILE.write_text("\n".join(lines[-MAX_LOG_LINES:]) + "\n", encoding="utf-8")
