"""Tests for open-in-browser review flow."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "greenhouse"
FORM_FIXTURE = FIXTURES_DIR / "application_form.html"


@pytest.fixture
def fixture_server():
    import threading
    from http.server import HTTPServer, SimpleHTTPRequestHandler

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(FIXTURES_DIR), **kwargs)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/application_form.html"
    server.shutdown()


@pytest.mark.skipif(not FORM_FIXTURE.exists(), reason="Fixtures not available")
class TestOpenReviewBrowser:
    def test_headed_prepare_keeps_session_alive(self, fixture_server):
        pytest.importorskip("playwright")
        from app.services.application_assistant.browser_runner import (
            close_session,
            get_active_session,
            prepare_application,
            run_playwright,
        )
        from app.services.application_assistant.providers.greenhouse import GreenhouseAdapter

        app_id = "test_open_review_session"
        adapter = GreenhouseAdapter()

        async def _open():
            return await prepare_application(
                application_url=fixture_server,
                adapter=adapter,
                context={"profile": {"email": "jane@example.com"}, "answerLibrary": [], "reviewMode": True},
                app_id=app_id,
                headed=True,
            )

        result = run_playwright(_open(), timeout=120)
        try:
            assert result.get("browserOpen") is True, result
            assert get_active_session(app_id) is not None
        finally:
            asyncio.run(close_session(app_id))

    def test_force_reopen_launches_new_session(self, fixture_server):
        pytest.importorskip("playwright")
        from unittest.mock import patch

        from app.db.store import session_scope
        from app.services.application_assistant.browser_runner import (
            close_session,
            get_active_session,
            prepare_application,
            run_playwright,
        )
        from app.services.application_assistant.persistence import create_application_draft
        from app.services.application_assistant.providers.greenhouse import GreenhouseAdapter
        from app.services.application_assistant.qwen_agent import execute_application_open_review

        adapter = GreenhouseAdapter()
        app_id = "test_force_reopen"

        async def _seed_session():
            return await prepare_application(
                application_url=fixture_server,
                adapter=adapter,
                context={"profile": {"email": "jane@example.com"}, "answerLibrary": [], "reviewMode": True},
                app_id=app_id,
                headed=True,
            )

        run_playwright(_seed_session(), timeout=120)
        assert get_active_session(app_id) is not None

        with session_scope() as db:
            draft = create_application_draft(
                db,
                {
                    "id": app_id,
                    "jobId": "job_force_reopen",
                    "jobUrl": fixture_server,
                    "companyName": "Fixture Co",
                    "roleTitle": "Engineer",
                    "status": "needs_review",
                    "fields": [
                        {
                            "label": "Email",
                            "normalizedKey": "email",
                            "fieldType": "email",
                            "classification": "verified",
                            "proposedValue": "jane@example.com",
                            "filled": True,
                        }
                    ],
                },
            )
            app_id = draft["id"]

        async def _run(force: bool):
            with session_scope() as db:
                with patch(
                    "app.services.application_assistant.qwen_agent.detect_provider",
                    return_value=("greenhouse", adapter, True),
                ):
                    return await execute_application_open_review(db, app_id, force_reopen=force)

        short = asyncio.run(_run(False))
        assert short.get("alreadyOpen") is True

        reopened = asyncio.run(_run(True))
        try:
            assert reopened.get("success") is True, reopened
            assert reopened.get("browserOpen") is True, reopened
            assert reopened.get("alreadyOpen") is not True
            assert get_active_session(app_id) is not None
        finally:
            asyncio.run(close_session(app_id))
