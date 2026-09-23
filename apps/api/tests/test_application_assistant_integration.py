"""Integration tests for Application Assistant — requires Playwright."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "greenhouse"
FORM_FIXTURE = FIXTURES_DIR / "application_form.html"


@pytest.fixture(autouse=True)
def _no_local_llm(monkeypatch):
    """Keep these tests off the local Ollama model.

    The fill step asks the model three times per run. With Ollama stopped, each
    ask waited ~10s for qwen and then mistral to refuse the connection (~40s a
    test); with Ollama running it loaded multi-GB models and timed out under
    load, which is why these tests were skipped as flaky. Neither outcome is
    what they test. With the local model off (and Gemini already off for the
    suite in conftest), the client reports itself unavailable and the fill runs
    its deterministic path.
    """
    from app.services.application_assistant import llm_client

    monkeypatch.setattr(llm_client, "LOCAL_LLM_ENABLED", False)


@pytest.fixture
def fixture_site():
    """Simple HTTP server serving Greenhouse fixtures, recording each path requested."""
    import threading
    from http.server import HTTPServer, SimpleHTTPRequestHandler
    from types import SimpleNamespace

    requested: list[str] = []

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(FIXTURES_DIR), **kwargs)

        def do_GET(self):
            requested.append(self.path)
            super().do_GET()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield SimpleNamespace(url=f"http://127.0.0.1:{port}/application_form.html", requested=requested)
    server.shutdown()


@pytest.fixture
def fixture_server(fixture_site):
    return fixture_site.url


@pytest.mark.skipif(not FORM_FIXTURE.exists(), reason="Fixtures not available")
class TestApplicationAssistantIntegration:
    def test_submission_never_clicked(self, fixture_site):
        """Prove that automation never clicks the final submit button.

        The fixture form reports a submit to the serving harness, so a click
        during the fill is recorded here even after that browser has closed.
        """
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
                application_url=fixture_site.url,
                adapter=adapter,
                context={"profile": profile, "answerLibrary": [], "allowInferred": False},
                app_id="test_integration",
                headed=False,
            )

        result = asyncio.run(_run())
        assert result.get("success") is True or result.get("fields")
        assert "/application_form.html" in fixture_site.requested, "fill never loaded the form"
        assert "/__submit_clicked" not in fixture_site.requested, (
            "Submit button must never be clicked by automation"
        )

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
