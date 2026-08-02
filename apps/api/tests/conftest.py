"""Shared pytest configuration."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TEST_STATE_DIR = Path(tempfile.mkdtemp(prefix="careeros-tests-"))
_TEST_ENV = {
    "CAREER_OS_DATABASE_URL": f"sqlite:///{(_TEST_STATE_DIR / 'career_os.db').as_posix()}",
    "AA_BROWSER_PROFILE_DIR": str(_TEST_STATE_DIR / "browser-profile"),
    "CAREER_OS_SKIP_EXTENSION_SEED": "1",
}
_PREVIOUS_ENV = {key: os.environ.get(key) for key in _TEST_ENV}
os.environ.update(_TEST_ENV)


@pytest.fixture(scope="session", autouse=True)
def initialize_database() -> None:
    """Run the entire suite against an isolated SQLite database and browser profile."""
    from app.db.store import engine, init_db

    init_db()
    yield

    try:
        from app.services.application_assistant.browser_runner import shutdown_playwright_worker

        shutdown_playwright_worker()
    except ImportError:
        pass
    engine.dispose()
    for key, previous in _PREVIOUS_ENV.items():
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous
    shutil.rmtree(_TEST_STATE_DIR, ignore_errors=True)
