"""Tests for saved browser replay plans."""

from app.services.application_assistant.browser_replay import (
    autofill_state_metadata,
    build_browser_plan,
    build_replay_actions_from_fields,
    effective_autofill_step_count,
    ensure_document_upload_actions,
    ensure_replay_plan,
    has_persisted_autofill_plan,
    hydrate_fill_actions,
    merge_plan_actions_with_fields,
    plan_is_usable,
    quick_apply_info,
    sort_fill_actions,
    summarize_application_list_item,
)


class TestBrowserReplay:
    def test_build_and_validate_plan(self):
        plan = build_browser_plan(
            nav_url="https://boards.greenhouse.io/acme/jobs/1",
            source_url="https://careers.acme.com/jobs/1",
            provider="greenhouse",
            fill_actions=[
                {
                    "type": "text",
                    "selector": "#first_name",
                    "fieldId": "f1",
                    "fieldLabel": "First Name",
                    "value": "Ada",
                }
            ],
            use_iframe=True,
        )
        assert plan_is_usable(plan)
        assert plan["actionCount"] == 1

    def test_build_plan_stores_form_nav_url(self):
        plan = build_browser_plan(
            nav_url="https://job-boards.greenhouse.io/datadog/jobs/1",
            form_nav_url="https://job-boards.greenhouse.io/datadog/jobs/1#app",
            source_url="https://careers.datadoghq.com/detail/1",
            provider="greenhouse",
            fill_actions=[{"type": "text", "selector": "#first_name", "value": "Ada"}],
        )
        assert plan["formNavUrl"] == "https://job-boards.greenhouse.io/datadog/jobs/1#app"
        assert plan["navUrl"] == "https://job-boards.greenhouse.io/datadog/jobs/1"

    def test_merge_plan_actions_hydrates_values_from_saved_fields(self):
        plan_actions = [
            {
                "type": "fill_field",
                "selector": "#email",
                "fieldId": "field_email",
                "normalizedKey": "email",
                "fieldType": "select-one",
                "value": "old@example.com",
            }
        ]
        saved_fields = [
            {
                "fieldId": "field_email",
                "normalizedKey": "email",
                "selectorHint": "#email",
                "proposedValue": "new@example.com",
                "classification": "verified",
                "fieldType": "select-one",
            },
            {
                "fieldId": "field_first_name",
                "normalizedKey": "first_name",
                "selectorHint": "#first_name",
                "proposedValue": "Ada",
                "classification": "verified",
                "fieldType": "select-one",
            },
        ]
        merged = merge_plan_actions_with_fields(plan_actions, saved_fields)
        by_key = {action["normalizedKey"]: action for action in merged}
        assert by_key["email"]["value"] == "new@example.com"
        assert by_key["email"]["fieldType"] == "email"
        assert by_key["first_name"]["value"] == "Ada"
        assert by_key["first_name"]["fieldType"] == "text"

    def test_hydrate_updates_values_from_saved_fields(self):
        plan_actions = [
            {
                "type": "text",
                "selector": "#email",
                "fieldId": "f2",
                "fieldLabel": "Email",
                "value": "old@example.com",
            }
        ]
        saved = [{"fieldId": "f2", "proposedValue": "new@example.com", "selectorHint": "#email"}]
        hydrated = hydrate_fill_actions(plan_actions, saved)
        assert hydrated[0]["value"] == "new@example.com"

    def test_hydrate_maps_resume_path_to_file_path(self):
        plan_actions = [
            {
                "type": "upload_document",
                "selector": "#resume",
                "fieldId": "resume1",
                "filePath": "/tmp/stale.pdf",
            }
        ]
        saved = [
            {
                "fieldId": "resume1",
                "fieldType": "file",
                "proposedValue": "/tmp/current.pdf",
                "selectorHint": "#resume",
            }
        ]
        hydrated = hydrate_fill_actions(plan_actions, saved)
        assert hydrated[0]["filePath"] == "/tmp/current.pdf"

    def test_ensure_document_upload_actions_injects_missing_resume(self, tmp_path, monkeypatch):
        import base64

        import app.services.application_assistant.document_files as doc_mod

        monkeypatch.setattr(doc_mod, "DOCUMENT_CACHE_DIR", tmp_path)
        pdf = tmp_path / "resume.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF")
        fields = [
            {
                "fieldId": "resume1",
                "label": "Resume/CV *",
                "fieldType": "file",
                "selectorHint": "#resume",
                "classification": "verified",
            }
        ]
        context = {
            "documents": {
                "defaultResume": {
                    "name": "resume.pdf",
                    "type": "application/pdf",
                    "base64": base64.b64encode(pdf.read_bytes()).decode(),
                }
            }
        }
        actions = ensure_document_upload_actions([], fields, context)
        assert len(actions) == 1
        assert actions[0]["type"] == "upload_document"
        assert actions[0]["selector"] == "#resume"
        assert actions[0]["filePath"]

    def test_uploads_sort_first(self):
        actions = [
            {"fieldLabel": "Email", "type": "fill_field"},
            {"fieldLabel": "Resume/CV", "type": "upload_document"},
        ]
        ordered = sort_fill_actions(actions)
        assert ordered[0]["type"] == "upload_document"

    def test_phone_country_sorts_last(self):
        actions = [
            {"normalizedKey": "phone_country", "fieldLabel": "Country"},
            {"fieldLabel": "Phone", "normalizedKey": "phone"},
            {"fieldLabel": "First Name"},
        ]
        ordered = sort_fill_actions(actions)
        assert ordered[0]["fieldLabel"] == "First Name"
        assert ordered[-1]["normalizedKey"] == "phone_country"

    def test_rebuild_actions_from_saved_fields(self):
        fields = [
            {
                "label": "First Name*",
                "fieldId": "f1",
                "selectorHint": "#first_name",
                "proposedValue": "Ada",
                "classification": "verified",
                "filled": True,
                "fieldType": "text",
            }
        ]
        actions = build_replay_actions_from_fields(fields)
        assert len(actions) == 1
        plan = ensure_replay_plan(
            {"version": 1, "navUrl": "https://example.com", "fillActions": []},
            fields,
            nav_url="https://example.com",
        )
        assert plan_is_usable(plan)

    def test_saved_state_when_plan_empty_but_fields_replayable(self):
        draft = {
            "id": "app_reddit_1",
            "jobId": "aa_reddit_8082867",
            "status": "needs_review",
            "jobUrl": "https://job-boards.greenhouse.io/reddit/jobs/1",
            "browserPlan": {"version": 1, "navUrl": "https://job-boards.greenhouse.io/reddit/jobs/1", "fillActions": []},
            "fields": [
                {
                    "label": "Email*",
                    "selectorHint": "#email",
                    "proposedValue": "ada@example.com",
                    "classification": "verified",
                    "normalizedKey": "email",
                    "filled": True,
                }
            ],
        }
        info = quick_apply_info(draft)
        assert info["hasSavedAutofillState"] is True
        assert info["quickApplyAvailable"] is True
        assert info["prepRequired"] is False

    def test_reconcile_clears_stale_browser_run_when_browser_closed(self, monkeypatch):
        from unittest.mock import MagicMock

        from app.services.application_assistant.browser_replay import reconcile_stale_browser_run

        db = MagicMock()
        draft = {
            "id": "app_stuck",
            "status": "in_progress",
            "browserPlan": {
                "version": 1,
                "navUrl": "https://example.com/jobs/1",
                "fillActions": [{"selector": "#email", "value": "a@b.com", "type": "text"}],
                "actionCount": 1,
            },
        }
        active_run = {"id": "run_1", "status": "running", "startedAt": "2020-01-01T00:00:00+00:00"}
        monkeypatch.setattr(
            "app.services.application_assistant.browser_runner.get_active_session",
            lambda _app_id: None,
        )
        monkeypatch.setattr(
            "app.services.application_assistant.worker.task_status",
            lambda _task_id: "not_found",
        )

        result = reconcile_stale_browser_run(db, draft, active_run=active_run)

        assert result["status"] == "needs_review"

    def test_reconcile_clears_orphan_in_progress(self, monkeypatch):
        from unittest.mock import MagicMock

        from app.services.application_assistant.qwen_agent import reconcile_stale_prep_state

        db = MagicMock()
        draft = {"id": "app_orphan", "status": "in_progress"}
        monkeypatch.setattr(
            "app.services.application_assistant.qwen_agent.task_status",
            lambda _task_id: "not_found",
        )
        monkeypatch.setattr("app.services.application_assistant.qwen_agent.is_app_locked", lambda _app_id: False)
        monkeypatch.setattr("app.services.application_assistant.qwen_agent.get_agent_run", lambda _db, _app_id: None)
        monkeypatch.setattr(
            "app.services.application_assistant.qwen_agent.get_active_browser_run_for_app",
            lambda _db, _app_id: None,
        )
        monkeypatch.setattr(
            "app.services.application_assistant.browser_replay.reconcile_stale_browser_run",
            lambda _db, d, **kwargs: d,
        )

        result = reconcile_stale_prep_state(db, draft)
        assert result["status"] == "ready_to_prepare"

    def test_saved_state_when_plan_has_actions(self):
        plan = build_browser_plan(
            nav_url="https://job-boards.greenhouse.io/reddit/jobs/1",
            source_url="https://job-boards.greenhouse.io/reddit/jobs/1",
            provider="greenhouse",
            fill_actions=[{"type": "fill_field", "selector": "#email", "value": "ada@example.com"}],
        )
        draft = {
            "id": "app_169b0429",
            "jobId": "aa_reddit_8082867",
            "status": "needs_review",
            "browserPlan": plan,
        }
        assert has_persisted_autofill_plan(draft) is True
        meta = autofill_state_metadata(draft)
        assert meta["hasSavedAutofillState"] is True
        assert meta["quickApplyAvailable"] is True
        assert meta["applicationId"] == "app_169b0429"
        assert meta["jobId"] == "aa_reddit_8082867"
        assert meta["autofillStepCount"] == 1

    def test_submitted_application_disables_quick_apply(self):
        plan = build_browser_plan(
            nav_url="https://job-boards.greenhouse.io/reddit/jobs/1",
            source_url="https://job-boards.greenhouse.io/reddit/jobs/1",
            provider="greenhouse",
            fill_actions=[{"type": "fill_field", "selector": "#email", "value": "ada@example.com"}],
        )
        draft = {
            "id": "app_169b0429",
            "jobId": "aa_reddit_8082867",
            "status": "submitted_manually",
            "browserPlan": plan,
        }
        meta = autofill_state_metadata(draft)
        assert meta["quickApplyAvailable"] is False
        assert meta["quickApplyLabel"] == "Submitted"
        row = summarize_application_list_item(draft)
        assert row["quickApplyAvailable"] is False

    def test_list_summary_keeps_autofill_flags_without_browser_plan_blob(self):
        plan = build_browser_plan(
            nav_url="https://job-boards.greenhouse.io/datadog/jobs/1",
            source_url="https://job-boards.greenhouse.io/datadog/jobs/1",
            provider="greenhouse",
            fill_actions=[{"type": "fill_field", "selector": "#email", "value": "ada@example.com"}],
        )
        draft = {
            "id": "app_datadog",
            "jobId": "aa_datadog_1",
            "status": "needs_review",
            "browserPlan": plan,
        }
        row = summarize_application_list_item(draft)
        assert "browserPlan" not in row
        assert row["hasSavedAutofillState"] is True
        assert row["quickApplyAvailable"] is True
        assert "Start prep" not in row["quickApplyLabel"]

    def test_zero_saved_steps_not_quick_apply_ready(self):
        draft = {
            "id": "app_empty",
            "jobId": "job_empty",
            "status": "needs_review",
            "browserPlan": {"version": 1, "navUrl": "https://example.com", "fillActions": []},
            "fields": [],
        }
        assert effective_autofill_step_count(draft) == 0
        assert has_persisted_autofill_plan(draft) is False
        meta = autofill_state_metadata(draft)
        assert meta["hasSavedAutofillState"] is False
        assert meta["quickApplyAvailable"] is False
        assert meta["prepRequired"] is True
        assert meta["quickApplyStepCount"] == 0
