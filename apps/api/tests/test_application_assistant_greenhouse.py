"""Adapter tests for Greenhouse provider using local HTML fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.application_assistant.providers.greenhouse import GreenhouseAdapter
from app.services.application_assistant.submission_guard import is_prohibited_action

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "greenhouse"


class TestGreenhouseAdapterDetection:
    def setup_method(self):
        self.adapter = GreenhouseAdapter()

    def test_detects_greenhouse_url(self):
        result = self.adapter.detect("https://boards.greenhouse.io/testcompany")
        assert result.provider == "greenhouse"
        assert result.supported is True
        assert result.confidence > 0.5

    def test_does_not_detect_unknown(self):
        result = self.adapter.detect("https://example.com/careers")
        assert result.confidence < 0.5


class TestGreenhouseUrlResolution:
    def test_resolves_datadog_careers_page(self):
        from app.services.application_assistant.providers.greenhouse import resolve_greenhouse_apply_url

        url = "https://careers.datadoghq.com/detail/8088589/?gh_jid=8088589"
        resolved = resolve_greenhouse_apply_url(url, company_name="Datadog")
        assert resolved == "https://careers.datadoghq.com/detail/8088589/?gh_jid=8088589"

    def test_keeps_direct_greenhouse_url(self):
        from app.services.application_assistant.providers.greenhouse import resolve_greenhouse_apply_url

        url = "https://job-boards.greenhouse.io/reddit/jobs/8082867"
        assert resolve_greenhouse_apply_url(url) == url

    def test_resolves_job_boards_form_nav_url(self):
        from app.services.application_assistant.providers.greenhouse import resolve_greenhouse_form_nav_url

        url = "https://job-boards.greenhouse.io/datadog/jobs/8088589?gh_jid=8088589"
        source = "https://careers.datadoghq.com/detail/8088589/?gh_jid=8088589"
        assert resolve_greenhouse_form_nav_url(url, source_url=source) == (
            "https://careers.datadoghq.com/detail/8088589/?gh_jid=8088589#app"
        )

    def test_upgrades_embed_nav_to_careers_page(self):
        from app.services.application_assistant.providers.greenhouse import resolve_greenhouse_form_nav_url

        embed = "https://boards.greenhouse.io/embed/job_app?for=datadog&token=8088589"
        source = "https://careers.datadoghq.com/detail/8088589/?gh_jid=8088589"
        assert resolve_greenhouse_form_nav_url(embed, source_url=source) == (
            "https://careers.datadoghq.com/detail/8088589/?gh_jid=8088589#app"
        )

    def test_keeps_job_boards_form_nav_without_careers_wrapper(self):
        from app.services.application_assistant.providers.greenhouse import resolve_greenhouse_form_nav_url

        url = "https://job-boards.greenhouse.io/reddit/jobs/8082867?gh_jid=8082867"
        assert resolve_greenhouse_form_nav_url(url) == (
            "https://job-boards.greenhouse.io/reddit/jobs/8082867?gh_jid=8082867#app"
        )


class TestGreenhouseAdapterMapping:
    def setup_method(self):
        self.adapter = GreenhouseAdapter()

    def test_maps_contact_fields(self):
        from app.services.application_assistant.providers.base import FormField

        fields = [
            FormField(label="First Name", normalized_key="first_name", field_type="text", required=True),
            FormField(label="Email", normalized_key="email", field_type="email", required=True),
            FormField(label="LinkedIn Profile", normalized_key="linkedin_profile", field_type="url"),
        ]
        profile = {
            "firstName": "Jane",
            "email": "jane@example.com",
            "linkedin": "https://linkedin.com/in/jane",
        }
        mapped = self.adapter.map_fields(fields, {"profile": profile})
        assert len(mapped) == 3
        assert mapped[0]["classification"] == "verified"
        assert mapped[0]["proposedValue"] == "Jane"
        assert mapped[1]["proposedValue"] == "jane@example.com"

    def test_sensitive_fields_not_inferred(self):
        from app.services.application_assistant.providers.base import FormField

        fields = [
            FormField(label="Salary Expectations", normalized_key="salary", field_type="text"),
            FormField(label="Are you authorized to work?", normalized_key="work_auth", field_type="select"),
        ]
        mapped = self.adapter.map_fields(fields, {"profile": {}})
        assert mapped[0]["classification"] == "unknown"
        assert mapped[1]["classification"] == "unknown"

    def test_manual_only_declaration(self):
        from app.services.application_assistant.providers.base import FormField

        fields = [
            FormField(label="I certify that the information is accurate", normalized_key="cert", field_type="checkbox"),
            FormField(label="Electronic Signature", normalized_key="sig", field_type="text"),
        ]
        mapped = self.adapter.map_fields(fields, {"profile": {"fullName": "Jane Doe"}})
        assert all(m["classification"] == "manual_only" for m in mapped)


class TestGreenhouseSubmitDetection:
    def test_submit_button_is_prohibited(self):
        assert is_prohibited_action("Submit Application", provider="greenhouse") is True

    def test_save_and_continue_is_safe(self):
        from app.services.application_assistant.submission_guard import is_safe_navigation
        assert is_safe_navigation("Save and Continue") is True


@pytest.mark.skipif(
    not (FIXTURES_DIR / "application_form.html").exists(),
    reason="Fixtures not available",
)
class TestGreenhouseFixturesExist:
    def test_fixtures_present(self):
        assert (FIXTURES_DIR / "careers_list.html").exists()
        assert (FIXTURES_DIR / "job_detail.html").exists()
        assert (FIXTURES_DIR / "application_form.html").exists()

    def test_application_form_has_submit_button(self):
        content = (FIXTURES_DIR / "application_form.html").read_text()
        assert "Submit Application" in content
        assert "submit_app" in content

    def test_application_form_has_contact_fields(self):
        content = (FIXTURES_DIR / "application_form.html").read_text()
        assert 'name="first_name"' in content
        assert 'name="email"' in content
        assert 'name="resume"' in content

    def test_application_form_has_sensitive_sections(self):
        content = (FIXTURES_DIR / "application_form.html").read_text()
        assert "work_auth" in content
        assert "salary" in content
        assert "electronic_signature" in content

    def test_submit_tracking_script(self):
        content = (FIXTURES_DIR / "application_form.html").read_text()
        assert "__submitClicked" in content
