"""Shared persistent state for both overnight loops.

Everything is a small JSON file written atomically (temp file + rename), plus an
append-only JSONL event log. Two processes share it: the supervisor (Loop A) and
the improver (Loop B). Each owns its own section of state, so they never write
the same file; `session.json` is written only by the CLI.

Layout under the state directory (default `apps/api/data/overnight/`):

    session.json      desired state of the session (armed, flags), CLI-owned
    supervisor.json   Loop A: last cycle, counts, next check, resume budget
    improver.json     Loop B: current group, step, fixes, blockers, requeues
    groups.json       last computed failure groups (Loop B writes)
    events.jsonl      append-only event log, both loops
    locks/*.lock      process locks (one supervisor, one improver)
    stop              presence asks both loops to exit at their next boundary
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

API_DIR = Path(__file__).resolve().parents[3]
DEFAULT_STATE_DIR = API_DIR / "data" / "overnight"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        import psutil

        return psutil.pid_exists(int(pid))
    except ImportError:  # pragma: no cover - psutil is a dependency here
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False


class LockHeld(RuntimeError):
    """Another live process holds the lock."""


@dataclass
class StateStore:
    root: Path = DEFAULT_STATE_DIR

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        (self.root / "locks").mkdir(parents=True, exist_ok=True)

    # ---- JSON documents -------------------------------------------------
    def path(self, name: str) -> Path:
        return self.root / name

    def read(self, name: str, default: Any = None) -> Any:
        try:
            return json.loads(self.path(name).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {} if default is None else default
        except json.JSONDecodeError as exc:
            # A half-written file cannot happen with atomic writes; if one is
            # corrupt, say so loudly instead of silently starting from empty.
            raise RuntimeError(f"Overnight state file {self.path(name)} is corrupt: {exc}") from exc

    def write(self, name: str, data: Any) -> None:
        atomic_write_json(self.path(name), data)

    def update(self, name: str, **fields: Any) -> dict[str, Any]:
        doc = self.read(name)
        doc.update(fields)
        self.write(name, doc)
        return doc

    # ---- events ---------------------------------------------------------
    def event(self, loop: str, kind: str, message: str, **data: Any) -> dict[str, Any]:
        entry = {"at": now_iso(), "loop": loop, "kind": kind, "message": message, **data}
        with self.path("events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
        return entry

    def events(self, since: datetime | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            lines = self.path("events.jsonl").read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return out
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if since is not None:
                at = parse_iso(entry.get("at"))
                if at is None or at < since:
                    continue
            out.append(entry)
        return out

    # ---- stop flag ------------------------------------------------------
    def stop_requested(self) -> bool:
        return self.path("stop").exists()

    def request_stop(self) -> None:
        self.path("stop").write_text(now_iso(), encoding="utf-8")

    def clear_stop(self) -> None:
        self.path("stop").unlink(missing_ok=True)

    # ---- locks ----------------------------------------------------------
    @contextmanager
    def lock(self, name: str, label: str) -> Iterator[Path]:
        path = self.path(f"locks/{name}.lock")
        acquire_file_lock(path, label)
        try:
            yield path
        finally:
            release_file_lock(path)

    def lock_holder(self, name: str) -> dict[str, Any] | None:
        return live_lock_holder(self.path(f"locks/{name}.lock"))


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, default=str))


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        # os.replace is atomic on Windows and POSIX; a reader sees the old or
        # the new file, never a partial one. Windows refuses the replace while
        # another process has the target open, so retry briefly.
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# Same format and semantics as nightly-evolution's engine.lock (JSON with pid,
# host, label, at; created exclusively; stale when the holder is gone), so the
# improver can hold that lock too and the two improvement lanes never run an
# agent at the same time.
LOCK_STALE_SECONDS = 3 * 3600


def live_lock_holder(path: Path) -> dict[str, Any] | None:
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None if not path.exists() else {"label": "unreadable lock", "pid": None}
    at = parse_iso(held.get("at"))
    age = (datetime.now(timezone.utc) - at).total_seconds() if at else float("inf")
    stale = age > LOCK_STALE_SECONDS or (
        held.get("host") == socket.gethostname() and not pid_alive(held.get("pid"))
    )
    return None if stale else held


def acquire_file_lock(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mine = {"pid": os.getpid(), "host": socket.gethostname(), "label": label, "at": now_iso()}
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            held = live_lock_holder(path)
            if held:
                raise LockHeld(
                    f"{path.name} is held by {held.get('label')} (pid {held.get('pid')}, since {held.get('at')})"
                )
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(mine, fh)
        return
    raise LockHeld(f"Could not acquire {path}")


def release_file_lock(path: Path) -> None:
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return
    if held.get("pid") == os.getpid():
        path.unlink(missing_ok=True)


def memory_snapshot() -> dict[str, Any]:
    """RAM and CPU for the dashboard and the improver's resource gate."""
    try:
        import psutil

        vm = psutil.virtual_memory()
        return {
            "ramTotalMb": round(vm.total / 2**20),
            "ramAvailableMb": round(vm.available / 2**20),
            "ramPercent": vm.percent,
            "cpuPercent": psutil.cpu_percent(interval=0.2),
        }
    except Exception as exc:  # pragma: no cover - reported, never swallowed silently
        return {"error": f"resource probe failed: {exc}"}
