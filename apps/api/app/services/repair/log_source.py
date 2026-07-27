from __future__ import annotations

import uuid

from app.services.error_fix_tracker import error_fix_tracker
from app.services.log_store import read_client_logs
from app.services.repair.types import LogEntry, LogSource, ReadLogOptions


def _entry_from_tracked(item) -> LogEntry:
    endpoint = item.signature if item.signature.startswith(("GET ", "POST ", "PUT ", "PATCH ", "DELETE ")) else ""
    return LogEntry(
        id=item.id,
        level="error",
        source=item.source,
        message=item.message,
        timestamp=__import__("datetime").datetime.fromtimestamp(item.at, tz=__import__("datetime").timezone.utc).isoformat(),
        signature=item.signature,
        endpoint=endpoint,
        stack_trace=str((item.meta or {}).get("stackTrace") or ""),
        status_code=item.status_code,
        metadata={"fromHistory": True, **(item.meta or {})},
    )


class CareerOSLogSource:
    """Reads persisted CareerOS backend/client logs and error history from disk."""

    def read_recent_logs(self, options: ReadLogOptions | None = None) -> list[LogEntry]:
        opts = options or ReadLogOptions()
        entries: list[LogEntry] = []
        seen_ids: set[str] = set()

        def add_entry(entry: LogEntry) -> None:
            if entry.id in seen_ids:
                return
            seen_ids.add(entry.id)
            entries.append(entry)

        if opts.include_client_logs:
            for item in read_client_logs(limit=opts.limit):
                level = str(item.get("level") or "info").lower()
                if level not in {"error", "warning", "critical"}:
                    continue
                metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                add_entry(
                    LogEntry(
                        id=str(item.get("id") or uuid.uuid4().hex[:12]),
                        level=level,
                        source=str(item.get("source") or "client"),
                        message=str(item.get("message") or ""),
                        timestamp=str(item.get("ts") or ""),
                        signature=f"{item.get('source') or 'client'}:{item.get('module') or item.get('type') or 'log'}",
                        endpoint=str(metadata.get("endpoint") or ""),
                        stack_trace=str(metadata.get("stackTrace") or metadata.get("stack_trace") or ""),
                        metadata=metadata,
                    )
                )

        if opts.include_open_errors:
            for item in error_fix_tracker.list_open_errors():
                add_entry(_entry_from_tracked(item))

        if opts.include_error_history:
            for item in error_fix_tracker.list_persisted_errors(limit=opts.limit):
                add_entry(_entry_from_tracked(item))

        entries.sort(key=lambda entry: entry.timestamp or "")
        return entries[-opts.limit :]


def log_inventory() -> dict[str, int]:
    from app.services.log_store import LOG_FILE

    client_lines = 0
    if LOG_FILE.is_file():
        client_lines = sum(1 for line in LOG_FILE.read_text(encoding="utf-8").splitlines() if line.strip())
    inventory = error_fix_tracker.inventory()
    return {
        **inventory,
        "clientLogLines": client_lines,
    }


log_source: LogSource = CareerOSLogSource()
