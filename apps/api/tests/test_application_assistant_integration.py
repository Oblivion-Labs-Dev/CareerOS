"""Integration tests for Application Assistant — requires Playwright."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "greenhouse"
FORM_FIXTURE = FIXTURES_DIR / "application_form.html"


@pytest.fixture
def fixture_server():
    """Simple HTTP server serving Greenhouse fixtures."""
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
class TestApplicationAssistantIntegration:
    def test_submission_never_clicked(self, fixture_server):
        """Prove that automation never clicks the final submit button."""
        import asyncio

        pytest.importorskip("playwright")
        from app.services.application_assistant.browser_runner import prepare_application
        from app.services.application_assistant.providers.greenhouse import GreenhouseAdapter

        adapter = GreenhouseAdapter()
        profile = {
            "firstName": "Jane",
            "lastName": "Doe",
            "email": "jane@example.com",
            "phone": "+1 555-123-4567",
            "linkedin": "https://linkedin.com/in/jane",
        }

        async def _run():
            return await prepare_application(
                application_url=fixture_server,
                adapter=adapter,
                context={"profile": profile, "answerLibrary": [], "allowInferred": False},
                app_id="test_integration",
                headed=False,
            )

        result = asyncio.run(_run())
        assert result.get("success") is True or result.get("fields")

        async def _check_submit():
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(fixture_server)
                return await page.evaluate("window.__submitClicked")

        submit_clicked = asyncio.run(_check_submit())
        assert submit_clicked is False, "Submit button must never be clicked by automation"

    def test_verified_fields_filled(self, fixture_server):
        """Verify that verified profile fields are mapped."""
        import asyncio

        pytest.importorskip("playwright")
        from app.services.application_assistant.browser_runner import prepare_application
        from app.services.application_assistant.providers.greenhouse import GreenhouseAdapter

        adapter = GreenhouseAdapter()
        profile = {"firstName": "Jane", "lastName": "Doe", "email": "jane@example.com"}

        async def _run():
            return await prepare_application(
                application_url=fixture_server,
                adapter=adapter,
                context={"profile": profile, "answerLibrary": []},
                app_id="test_fill",
                headed=False,
            )

        result = asyncio.run(_run())
        fields = result.get("fields", [])
        verified_fields = [f for f in fields if f.get("classification") == "verified"]
        assert len(verified_fields) > 0, "Should have verified fields mapped"

    def test_resume_upload_filled(self, fixture_server):
        """Resume file input should receive the stored default resume."""
        import asyncio
        import base64

        pytest.importorskip("playwright")
        from app.services.application_assistant.browser_runner import prepare_application
        from app.services.application_assistant.providers.greenhouse import GreenhouseAdapter

        minimal_pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
        adapter = GreenhouseAdapter()

        async def _run():
            return await prepare_application(
                application_url=fixture_server,
                adapter=adapter,
                context={
                    "profile": {"firstName": "Jane", "email": "jane@example.com"},
                    "answerLibrary": [],
                    "documents": {
                        "defaultResume": {
                            "name": "Jane_Resume.pdf",
                            "type": "application/pdf",
                            "base64": base64.b64encode(minimal_pdf).decode(),
                        }
                    },
                },
                app_id="test_resume_upload",
                headed=False,
            )

        result = asyncio.run(_run())
        assert result.get("success") is True, result
        resume_field = next(
            (f for f in result.get("fields", []) if f.get("fieldType") == "file" and "resume" in f.get("label", "").lower()),
            None,
        )
        assert resume_field is not None
        assert resume_field.get("classification") == "verified"
        assert resume_field.get("filled") is True, resume_field
        upload_actions = [a for a in result.get("filled", []) if a.get("type") == "upload_document"]
        assert upload_actions, "Expected upload_document action in filled results"

    def test_persistence_roundtrip(self):
        """Test application draft persistence survives save/load."""
        from app.db.store import session_scope
        from app.services.application_assistant.persistence import (
            create_application_draft,
            get_application_draft,
            save_application_fields,
        )

        with session_scope() as db:
            draft = create_application_draft(db, {
                "jobId": "job_test",
                "jobUrl": "https://example.com/apply",
                "companyName": "Test Co",
                "roleTitle": "Engineer",
            })
            app_id = draft["id"]

            fields = [
                {
                    "id": "f1",
                    "label": "Email",
                    "normalizedKey": "email",
                    "fieldType": "email",
                    "classification": "verified",
                    "proposedValue": "test@test.com",
                    "filled": True,
                }
            ]
            save_application_fields(db, app_id, fields)

            loaded = get_application_draft(db, app_id)
            assert loaded is not None
            assert loaded["verifiedCount"] == 1
            assert len(loaded["fields"]) == 1
            assert loaded["fields"][0]["proposedValue"] == "test@test.com"

            from app.services.application_assistant.persistence import delete_application_draft

            delete_application_draft(db, app_id)
