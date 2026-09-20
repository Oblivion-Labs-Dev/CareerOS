"""GET/POST /api/db — the Chrome extension's full sync endpoint.

Two handlers were once registered for this exact path. FastAPI matches routes
in registration order, so a narrower pair added later — reading and writing
only `profile` and `documents` — silently shadowed the fuller implementation
underneath it on every single request. Two real consequences followed, neither
caught by any existing test because none exercised this route at all:

1. **Silent data loss.** The extension's sync (apps/extension/src/db/sync.ts)
   POSTs applications, jobs, learnedAnswers, sessions, fieldMappings,
   activityEvents and settings on every write. The shadowing handler kept only
   profile and documents; everything else was accepted with a 200 and quietly
   discarded.
2. **A silent authorization bypass.** The real handler is guarded by
   `require_legacy_sync_auth`, which requires `x-career-os-api-key` to match
   `CAREER_OS_API_KEY` whenever `CAREER_OS_DEV_MODE` is off. The shadowing
   handler had no auth check of any kind, so the guard was dead code as long
   as the shadow existed.

This file pins both: a full sync must actually persist everything sent, and
the auth guard must actually run.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.store import session_scope, set_kv
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_legacy_sync_settings():
    """Every test in this file cares about dev-mode/API-key state, so pin it
    to a known value rather than trusting whatever .env left it at, and put it
    back afterward."""
    original_dev_mode = settings.career_os_dev_mode
    original_api_key = settings.career_os_api_key
    yield
    settings.career_os_dev_mode = original_dev_mode
    settings.career_os_api_key = original_api_key


def test_full_sync_persists_more_than_profile_and_documents():
    settings.career_os_dev_mode = True  # auth guard is a no-op; not under test here

    payload = {
        "profile": {"email": "case@example.com"},
        "documents": {"defaultResume": {"name": "resume.pdf"}},
        "applications": [{"id": "app_1", "companyName": "Acme", "status": "saved"}],
        "jobs": [{"id": "job_1", "companyName": "Acme", "title": "Engineer"}],
        "settings": {"theme": "dark"},
    }

    response = client.post("/api/db", json=payload)
    assert response.status_code == 200, response.text

    with session_scope() as db:
        from app.db.store import get_kv, list_entities

        assert get_kv(db, "profile").get("email") == "case@example.com"
        assert get_kv(db, "settings").get("theme") == "dark", (
            "settings sent by the extension must not be silently dropped"
        )
        job_ids = [j.get("id") for j in list_entities(db, "job")]
        assert "job_1" in job_ids, "jobs sent by the extension must not be silently dropped"


def test_get_db_returns_the_full_snapshot_shape():
    with session_scope() as db:
        set_kv(db, "settings", {"theme": "light"})

    response = client.get("/api/db")
    assert response.status_code == 200
    body = response.json()

    # The narrower shadow handler never returned these two keys at all.
    assert "settings" in body
    assert "referrals" in body


def test_full_sync_is_rejected_without_an_api_key_outside_dev_mode():
    """The regression this file exists for: the shadowing handler accepted
    this write unconditionally. The real one must not."""
    settings.career_os_dev_mode = False
    settings.career_os_api_key = "expected-key"

    response = client.post("/api/db", json={"profile": {"email": "nope@example.com"}})

    assert response.status_code == 401
    with session_scope() as db:
        from app.db.store import get_kv

        assert (get_kv(db, "profile") or {}).get("email") != "nope@example.com", (
            "a write with no API key must not reach the database outside dev mode"
        )


def test_full_sync_succeeds_with_the_correct_api_key_outside_dev_mode():
    settings.career_os_dev_mode = False
    settings.career_os_api_key = "expected-key"

    response = client.post(
        "/api/db",
        json={"profile": {"email": "authorized@example.com"}},
        headers={"x-career-os-api-key": "expected-key"},
    )

    assert response.status_code == 200
    with session_scope() as db:
        from app.db.store import get_kv

        assert get_kv(db, "profile").get("email") == "authorized@example.com"
