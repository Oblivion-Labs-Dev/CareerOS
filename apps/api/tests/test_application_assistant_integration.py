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


@pytest.fixture(scope="class")
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


MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.fixture(scope="class")
def filled(fixture_site):
    """One real fill of the fixture form, shared by the assertions below.

    Each assertion used to launch its own browser and fill the same form with a
    subset of this context, about 12 s apiece. One fill with the full context
    exercises everything each of them checked.
    """
    import asyncio
    import base64

    pytest.importorskip("playwright")
    from app.services.application_assistant import llm_client
    from app.services.application_assistant.browser_runner import prepare_application
    from app.services.application_assistant.providers.greenhouse import GreenhouseAdapter

    # See _no_local_llm: that fixture is function-scoped, so this class-scoped
    # run switches the model off itself.
    previous, llm_client.LOCAL_LLM_ENABLED = llm_client.LOCAL_LLM_ENABLED, False
    try:
        result = asyncio.run(prepare_application(
            application_url=fixture_site.url,
            adapter=GreenhouseAdapter(),
            context={
                "profile": {
                    "firstName": "Jane",
                    "lastName": "Doe",
                    "email": "jane@example.com",
                    "phone": "+1 555-123-4567",
                    "linkedin": "https://linkedin.com/in/jane",
                },
                "answerLibrary": [],
                "allowInferred": False,
                "documents": {
                    "defaultResume": {
                        "name": "Jane_Resume.pdf",
                        "type": "application/pdf",
                        "base64": base64.b64encode(MINIMAL_PDF).decode(),
                    }
                },
            },
            app_id="test_integration",
            headed=False,
        ))
    finally:
        llm_client.LOCAL_LLM_ENABLED = previous
    return result


@pytest.mark.skipif(not FORM_FIXTURE.exists(), reason="Fixtures not available")
class TestApplicationAssistantIntegration:
    def test_submission_never_clicked(self, filled, fixture_site):
        """Prove that automation never clicks the final submit button.

        The fixture form reports a submit to the serving harness, so a click
        during the fill is recorded here even after that browser has closed.
        """
        assert filled.get("success") is True or filled.get("fields")
        assert "/application_form.html" in fixture_site.requested, "fill never loaded the form"
        assert "/__submit_clicked" not in fixture_site.requested, (
            "Submit button must never be clicked by automation"
        )

    def test_verified_fields_filled(self, filled):
        """Verify that verified profile fields are mapped."""
        verified_fields = [f for f in filled.get("fields", []) if f.get("classification") == "verified"]
        assert len(verified_fields) > 0, "Should have verified fields mapped"

    def test_resume_upload_filled(self, filled):
        """Resume file input should receive the stored default resume."""
        assert filled.get("success") is True, filled
        resume_field = next(
            (f for f in filled.get("fields", []) if f.get("fieldType") == "file" and "resume" in f.get("label", "").lower()),
            None,
        )
        assert resume_field is not None
        assert resume_field.get("classification") == "verified"
        assert resume_field.get("filled") is True, resume_field
        upload_actions = [a for a in filled.get("filled", []) if a.get("type") == "upload_document"]
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
