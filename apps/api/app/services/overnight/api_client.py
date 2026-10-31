"""Thin clients for the two things the loops read: the live API and the DB.

The supervisor acts only through the normal HTTP API (the same routes the
console uses), so every runner guard — one loop, the live-apply gates, rate
limits, duplicate checks — stays in force. The DB is opened read-only for
grouping and counts; neither loop ever writes a job row directly.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.services.overnight.state import API_DIR

DEFAULT_BASE_URL = "http://127.0.0.1:4000/application-assistant"


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class Api(Protocol):
    def get(self, path: str) -> Any: ...
    def post(self, path: str, body: dict[str, Any] | None = None) -> Any: ...


@dataclass
class HttpApi:
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 60.0

    def _cookie(self) -> str:
        from app.config import settings
        from app.services.auth import SESSION_COOKIE_NAME, create_session_token

        return f"{SESSION_COOKIE_NAME}={create_session_token(settings.career_os_admin_username)}"

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body or {}).encode() if method == "POST" else None
        req = urllib.request.Request(
            self.base_url.rstrip("/") + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Cookie": self._cookie()},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                parsed = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                parsed = raw.decode(errors="replace")[:500]
            raise ApiError(f"{method} {path} -> HTTP {exc.code}", exc.code, parsed) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise ApiError(f"{method} {path} unreachable: {exc}") from exc
        return json.loads(raw or b"{}")

    def get(self, path: str) -> Any:
        return self._call("GET", path)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self._call("POST", path, body)


def api_server_processes() -> list[dict[str, Any]]:
    """Live API servers (uvicorn serving app.main) as {pid, cwd, reload}.

    A launcher shell (`cmd /c python -m uvicorn ...`) has the same command line
    as the server it starts; a match whose parent also matches is the child of
    such a wrapper, so only the outermost of each chain is counted.
    """
    import psutil

    matches: dict[int, dict[str, Any]] = {}
    for proc in psutil.process_iter(["pid", "ppid", "cmdline", "cwd"]):
        try:
            cmd = " ".join(proc.info.get("cmdline") or [])
        except Exception:
            continue
        if "uvicorn" in cmd and "app.main" in cmd:
            matches[proc.info["pid"]] = {
                "pid": proc.info["pid"],
                "ppid": proc.info.get("ppid"),
                "cwd": proc.info.get("cwd"),
                "reload": "--reload" in cmd,
            }
    return [m for m in matches.values() if m["ppid"] not in matches]


def live_api_dir() -> Path | None:
    """The working directory of the single live API server, if exactly one."""
    try:
        servers = [s for s in api_server_processes() if s.get("cwd")]
    except Exception:
        return None
    dirs = {str(Path(s["cwd"]).resolve()) for s in servers}
    return Path(dirs.pop()) if len(dirs) == 1 else None


def default_db_path() -> Path:
    """The DB the live API uses: a relative SQLite URL resolves against the live
    server's working directory (it may run from another worktree than this
    code), falling back to this tree's apps/api."""
    from app.config import settings

    url = settings.career_os_database_url
    if not url.startswith("sqlite:///"):
        raise RuntimeError(f"Overnight loops read SQLite only; got {url.split(':')[0]}")
    path = Path(url[len("sqlite:///"):])
    if path.is_absolute():
        return path
    return ((live_api_dir() or API_DIR) / path).resolve()


def read_jobs(db_path: Path | None = None) -> list[dict[str, Any]]:
    """Every autopilot job, read-only (WAL readers never block the writer)."""
    path = Path(db_path or default_db_path())
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        rows = conn.execute(
            "SELECT payload FROM entities WHERE entity_type = 'aa_autopilot_job'"
        ).fetchall()
    finally:
        conn.close()
    jobs = []
    for (payload,) in rows:
        try:
            jobs.append(json.loads(payload))
        except (TypeError, json.JSONDecodeError):
            continue
    return jobs


def status_counts(jobs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        status = str(job.get("status") or "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    return counts
