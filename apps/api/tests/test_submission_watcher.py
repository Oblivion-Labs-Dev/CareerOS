"""Tests for Playwright submission auto-detection helpers."""

from app.services.application_assistant.submission_watcher import (
    is_submission_confirmation_url,
    record_application_submission,
)


class TestSubmissionConfirmationUrl:
    def test_greenhouse_confirmation_path(self):
        url = "https://job-boards.greenhouse.io/datadog/jobs/8088589/confirmation"
        assert is_submission_confirmation_url(url)

    def test_greenhouse_application_id_query(self):
        url = "https://job-boards.greenhouse.io/reddit/jobs/8082867?application_id=abc-123"
        assert is_submission_confirmation_url(url)

    def test_thank_you_url(self):
        assert is_submission_confirmation_url("https://careers.example.com/thank-you-for-applying")

    def test_apply_form_not_confirmation(self):
        assert not is_submission_confirmation_url("https://job-boards.greenhouse.io/datadog/jobs/8088589")

    def test_greenhouse_embed_confirmation_query(self):
        url = "https://boards.greenhouse.io/embed/job_app?for=datadog&token=8088589&applied=1"
        assert is_submission_confirmation_url(url)

    def test_datadog_careers_not_apply_page(self):
        assert not is_submission_confirmation_url("https://careers.datadoghq.com/detail/8088589/?gh_jid=8088589#app")

    def test_embedded_careers_thank_you_text(self):
        from app.services.application_assistant.submission_watcher import _is_embedded_careers_confirmation

        url = "https://careers.datadoghq.com/detail/8088589/?gh_jid=8088589"
        body = "Thank you for applying to Datadog! We have received your application."
        assert _is_embedded_careers_confirmation(url, body)


class TestRecordApplicationSubmission:
    def test_marks_draft_submitted(self):
        import uuid

        from app.db.store import session_scope
        from app.services.application_assistant.persistence import (
            create_application_draft,
            delete_application_draft,
            get_application_draft,
        )

        job_id = f"test_submit_{uuid.uuid4().hex[:12]}"
        with session_scope() as db:
            draft = create_application_draft(
                db,
                {
                    "jobId": job_id,
                    "jobUrl": "https://example.com/apply",
                    "companyName": "Acme",
                    "roleTitle": "Engineer",
                    "status": "needs_review",
                },
            )
            app_id = draft["id"]

        assert record_application_submission(app_id, "greenhouse_confirmation", "https://example.com/thank-you")
        with session_scope() as db:
            updated = get_application_draft(db, app_id)
            assert updated["status"] == "submitted_manually"
            assert updated["submissionSource"] == "auto"
            assert updated["submissionTrigger"] == "greenhouse_confirmation"
            assert updated.get("submittedAt")
            delete_application_draft(db, app_id)
