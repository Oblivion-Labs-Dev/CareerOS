"""Shared pytest configuration."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_TEST_STATE_DIR = Path(tempfile.mkdtemp(prefix="careeros-tests-"))
_TEST_DISCOVER_DIR = _TEST_STATE_DIR / "job_discover"
_TEST_DISCOVER_DIR.mkdir(parents=True, exist_ok=True)

_TEST_ENV = {
    "CAREER_OS_DATABASE_URL": f"sqlite:///{(_TEST_STATE_DIR / 'career_os.db').as_posix()}",
    "AA_BROWSER_PROFILE_DIR": str(_TEST_STATE_DIR / "browser-profile"),
    "CAREER_OS_SKIP_EXTENSION_SEED": "1",
    # The database was already isolated, but the job-discovery snapshot file
    # resolved from __file__ and so pointed at the real data directory. Running
    # the suite truncated the live jobs_snapshot.json. Redirect it too.
    "CAREEROS_JOB_DISCOVER_DATA_DIR": str(_TEST_DISCOVER_DIR),
    # The optional Gemini layer is off for the whole suite, and the key is
    # blanked so that nothing can reach the real API even if a code path
    # ignores the flag. A test that wants Gemini behaviour fakes the transport
    # (see tests/test_gemini_gateway.py) - burning free-tier quota to prove
    # that a 429 is retried would prove it once, on one day's limits.
    "CAREEROS_GEMINI_ENABLED": "0",
    "GEMINI_API_KEY": "",
    # Run the suite as a fresh checkout does: with no admin password, so the
    # login gate is off. The gate is now deny-by-default, and `settings` reads
    # .env — so without this the developer's own password switched enforcement
    # on for the whole suite and 401'd every test that calls an endpoint
    # through TestClient. Twenty-one of them, none of which are about auth.
    #
    # Tests that *are* about the gate turn it on for themselves by patching
    # is_auth_configured (see test_auth_gate.py), which is the honest way round:
    # the behaviour under test is stated in the test rather than inherited from
    # whatever happens to be in the environment.
    "CAREER_OS_ADMIN_PASSWORD": "",
    # The approved baseline resume came from .env too, so resume tests read the
    # candidate's real PDF locally and failed on any clean machine (CI). Point
    # it at a file that does not exist: a test that needs a baseline uses the
    # synthetic one in tests/resume_baseline_fixture.py, which sets its own path.
    "CAREEROS_APPROVED_RESUME_PATH": str(_TEST_STATE_DIR / "no-approved-resume.pdf"),
    # No test may reach a local model. With the developer's Ollama configured,
    # scraper-import tests made a real qwen call and then hung on a SQLite lock;
    # a test that wants model behaviour fakes it, as with Gemini above.
    "CAREEROS_LOCAL_LLM": "off",
}
_PREVIOUS_ENV = {key: os.environ.get(key) for key in _TEST_ENV}
os.environ.update(_TEST_ENV)

# The embedding model is optional at runtime: semantic.py falls back to BM25
# when it cannot load. CI has the package but no cached weights, so it always
# takes the fallback, and the two tests that need real embeddings skip there.
# Locally the weights are cached, and importing the package pulls in torch:
# one resume test spent 11-15 s on a path CI never takes. Blocking the import
# keeps the default run on CI's path. Set CAREEROS_TEST_EMBEDDINGS=1 to run the
# real-embedding tests (tests/test_resume_ranking.py) on a machine with the model.
if os.environ.get("CAREEROS_TEST_EMBEDDINGS") != "1":
    sys.modules.setdefault("sentence_transformers", None)  # type: ignore[arg-type]


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
