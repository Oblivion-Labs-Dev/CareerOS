"""Unit tests for Application Assistant core modules."""


from app.services.application_assistant.answer_classification import (
    classify_answer,
    is_manual_only_field,
    match_profile_key,
    normalize_field_key,
)
from app.services.application_assistant.domain import AnswerClassification, SensitivityCategory
from app.services.application_assistant.job_matching import match_job
from app.services.application_assistant.log_redaction import redact_dict, redact_string, sanitize_url
from app.services.application_assistant.submission_guard import (
    classify_button,
    is_prohibited_action,
    is_safe_navigation,
    validate_action_allowed,
)
from app.services.application_assistant.url_validation import (
    detect_provider_from_url,
    is_prohibited_platform,
    validate_url,
)

# ── URL Validation ────────────────────────────────────────────────────────────

class TestUrlValidation:
    def test_valid_https_url(self):
        valid, reason = validate_url("https://boards.greenhouse.io/company")
        assert valid is True
        assert reason == ""

    def test_blocks_file_scheme(self):
        valid, reason = validate_url("file:///etc/passwd")
        assert valid is False
        assert "Blocked" in reason

    def test_blocks_javascript_scheme(self):
        valid, reason = validate_url("javascript:alert(1)")
        assert valid is False

    def test_blocks_linkedin(self):
        valid, reason = validate_url("https://www.linkedin.com/jobs/view/123")
        assert valid is False
        assert "linkedin" in reason.lower()

    def test_detects_greenhouse(self):
        assert detect_provider_from_url("https://boards.greenhouse.io/company") == "greenhouse"

    def test_detects_workday(self):
        assert detect_provider_from_url("https://company.myworkdayjobs.com/en-US/careers") == "workday"

    def test_prohibited_platform(self):
        assert is_prohibited_platform("https://www.indeed.com/job/123") is True


# ── Answer Classification ─────────────────────────────────────────────────────

class TestAnswerClassification:
    def test_verified_email_from_profile(self):
        profile = {"email": "jane@example.com", "firstName": "Jane"}
        cls, value, conf, source, _ = classify_answer(
            label="Email Address", profile=profile
        )
        assert cls == AnswerClassification.VERIFIED
        assert value == "jane@example.com"
        assert conf == 1.0

    def test_sensitive_work_auth_requires_verified(self):
        profile = {"workAuthorization": "Yes"}
        cls, value, _, _, sens = classify_answer(
            label="Are you legally authorized to work in the US?",
            profile=profile,
        )
        assert sens == SensitivityCategory.WORK_AUTHORIZATION
        assert cls == AnswerClassification.VERIFIED
        assert value == "Yes"

    def test_sensitive_without_profile_data_is_unknown(self):
        profile = {}
        cls, value, _, _, sens = classify_answer(
            label="What are your salary expectations?",
            profile=profile,
        )
        assert sens == SensitivityCategory.SALARY
        assert cls == AnswerClassification.UNKNOWN
        assert value is None

    def test_manual_only_signature(self):
        cls, _, _, _, _ = classify_answer(label="Electronic Signature")
        assert cls == AnswerClassification.MANUAL_ONLY

    def test_manual_only_consent_checkbox(self):
        assert is_manual_only_field("I certify that the information is accurate") is True

    def test_normalize_field_key(self):
        assert normalize_field_key("First Name *") == "first_name"

    def test_match_profile_key(self):
        assert match_profile_key("Email Address") == "email"
        assert match_profile_key("LinkedIn Profile") == "linkedin"
        assert match_profile_key("Name") == "fullName"
        assert (
            match_profile_key("Please provide the name of your current (or most recent) company")
            == "currentCompany"
        )

    def test_company_field_uses_current_company_not_full_name(self):
        profile = {
            "fullName": "Akshay Borse",
            "firstName": "Akshay",
            "lastName": "Borse",
            "currentCompany": "Microsoft",
        }
        cls, value, _, source, _ = classify_answer(
            label="Please provide the name of your current (or most recent) company",
            profile=profile,
        )
        assert cls == AnswerClassification.VERIFIED
        assert value == "Microsoft"
        assert source == "profile.currentCompany"

    def test_company_field_unknown_without_company_data(self):
        profile = {"fullName": "Akshay Borse", "firstName": "Akshay", "lastName": "Borse"}
        cls, value, _, _, _ = classify_answer(
            label="Please provide the name of your current (or most recent) company",
            profile=profile,
        )
        assert cls == AnswerClassification.UNKNOWN
        assert value is None


# ── Submission Guard ──────────────────────────────────────────────────────────

class TestSubmissionGuard:
    def test_prohibited_submit_application(self):
        assert classify_button("Submit Application") == "prohibited"
        assert is_prohibited_action("Submit Application") is True

    def test_prohibited_send_application(self):
        assert is_prohibited_action("Send Application") is True

    def test_prohibited_complete_application(self):
        assert is_prohibited_action("Complete Application") is True

    def test_safe_navigation_continue(self):
        assert is_safe_navigation("Save and Continue") is True
        assert is_safe_navigation("Next") is True

    def test_manual_only_agree(self):
        from app.services.application_assistant.domain import ButtonClassification
        assert classify_button("I Agree") == ButtonClassification.MANUAL_ONLY

    def test_validate_fill_text_allowed(self):
        allowed, reason = validate_action_allowed("fill_text")
        assert allowed is True

    def test_validate_prohibited_click(self):
        allowed, reason = validate_action_allowed(
            "click_safe_nav", button_text="Submit Application"
        )
        assert allowed is False
        assert "Prohibited" in reason

    def test_validate_safe_nav_allowed(self):
        allowed, _ = validate_action_allowed(
            "click_safe_nav", button_text="Save and Continue"
        )
        assert allowed is True


# ── Job Matching ──────────────────────────────────────────────────────────────

class TestJobMatching:
    def test_match_with_skill_overlap(self):
        job = {
            "id": "job_1",
            "title": "Senior Python Engineer",
            "description": "Required: 5+ years Python experience. Preferred: Kubernetes.",
            "location": "Remote",
        }
        profile = {
            "yearsExperience": "6",
            "currentTitle": "Senior Engineer",
            "workExperience": [
                {"jobTitle": "Engineer", "company": "Co", "description": "Python, distributed systems, Kubernetes"}
            ],
        }
        result = match_job(job, profile)
        assert result["overallScore"] > 0
        assert "python" in [s.lower() for s in result["strongMatches"]]

    def test_match_does_not_reject_low_score(self):
        job = {
            "id": "job_2",
            "title": "VP Engineering",
            "description": "Required: 15+ years leadership. Required: MBA.",
            "location": "On-site NYC",
        }
        profile = {"yearsExperience": "2", "currentTitle": "Junior Developer"}
        result = match_job(job, profile)
        assert result["overallScore"] >= 0  # Score computed, not rejected

    def test_match_uses_comma_separated_skills(self):
        job = {
            "id": "job_3",
            "title": "Backend Engineer",
            "description": "Must know Python and PostgreSQL.",
            "location": "Remote",
        }
        profile = {"skills": "Python, PostgreSQL, Redis"}
        result = match_job(job, profile)
        assert result["overallScore"] > 0
        assert "python" in result["strongMatches"]

    def test_match_uses_uploaded_resume_text(self):
        job = {
            "id": "job_4",
            "title": "Data Engineer",
            "description": "Experience with Spark and Airflow required.",
            "location": "Remote",
        }
        profile = {"skills": ""}
        documents = {
            "defaultResume": {
                "parsedText": "Built Spark pipelines orchestrated with Airflow for analytics platforms.",
            }
        }
        result = match_job(job, profile, documents=documents)
        assert result["matchSources"]["resume"] is True
        assert result["overallScore"] > 0
        assert "spark" in result["strongMatches"] or "airflow" in result["strongMatches"]


class TestQwenJobMatch:
    def test_qwen_score_used_when_llm_available(self):
        import asyncio

        from app.services.application_assistant.llm_client import LLMClient
        from app.services.application_assistant.qwen_job_match import score_job_fit_with_qwen

        class FakeClient(LLMClient):
            def __init__(self):
                super().__init__(base_url="http://localhost:11434/v1", model="qwen3:8b")

            async def complete(self, prompt, *, system="", response_schema=None):
                return {
                    "success": True,
                    "data": {
                        "overallScore": 82,
                        "strongMatches": ["Python", "Kubernetes"],
                        "missingQualifications": ["PhD"],
                        "potentialConcerns": [],
                        "explanation": "Strong backend fit with relevant stack.",
                        "confidence": 0.88,
                    },
                }

        job = {
            "id": "job_qwen",
            "title": "Senior Python Engineer",
            "description": "Python and Kubernetes required.",
            "location": "Remote",
        }
        profile = {
            "currentTitle": "Senior Engineer",
            "skills": "Python, Kubernetes",
            "yearsExperience": "8",
        }
        documents = {"defaultResume": {"parsedText": "Built Python microservices on Kubernetes."}}

        result = asyncio.run(score_job_fit_with_qwen(FakeClient(), job, profile, documents=documents))
        assert result is not None
        assert result["matchMethod"] == "qwen"
        assert result["overallScore"] == 82.0
        assert "Python" in result["strongMatches"]

    def test_qwen_falls_back_to_heuristic(self):
        import asyncio
        from unittest.mock import patch

        from app.services.application_assistant.llm_client import LLMClient
        from app.services.application_assistant.qwen_job_match import match_job_with_qwen_fallback

        class FailingClient(LLMClient):
            def __init__(self):
                super().__init__(base_url="http://localhost:11434/v1", model="qwen3:8b")

            async def complete(self, prompt, *, system="", response_schema=None):
                return {"success": False, "error": "offline"}

        job = {
            "id": "job_fb",
            "title": "Backend Engineer",
            "description": "Must know Python.",
            "location": "Remote",
        }
        profile = {"skills": "Python"}

        class FakeDb:
            pass

        db = FakeDb()

        with patch(
            "app.services.application_assistant.qwen_job_match.create_llm_client",
            return_value=FailingClient(),
        ), patch(
            "app.services.application_assistant.qwen_job_match.load_match_context",
            return_value=(profile, {}, []),
        ), patch(
            "app.services.application_assistant.qwen_job_match.get_settings",
            return_value={"llm": {}},
        ), patch(
            "app.services.application_assistant.qwen_job_match.qwen_activity.append_log",
            return_value={},
        ):
            result = asyncio.run(match_job_with_qwen_fallback(db, job, profile, use_qwen=True))

        assert result["matchMethod"] == "heuristic"
        assert result["overallScore"] > 0


# ── Log Redaction ─────────────────────────────────────────────────────────────

class TestLogRedaction:
    def test_redact_password(self):
        assert "***REDACTED***" in redact_string("password=secret123")

    def test_redact_dict_sensitive_keys(self):
        result = redact_dict({"workAuthorization": "Yes", "email": "test@test.com"})
        assert result["workAuthorization"] == "***REDACTED***"
        assert result["email"] == "test@test.com"

    def test_sanitize_url(self):
        url = sanitize_url("https://example.com/page?token=abc123&page=1")
        assert "token=***REDACTED***" in url
        assert "page=1" in url


# ── Application Draft Identity ────────────────────────────────────────────────

class TestApplicationDraftIdentity:
    def test_create_reuses_same_job_id(self):
        import uuid

        from app.db.store import session_scope
        from app.services.application_assistant.persistence import (
            application_id_for_job,
            create_application_draft,
            delete_application_draft,
            list_application_drafts,
        )

        job_id = f"test_identity_{uuid.uuid4().hex[:12]}"
        payload = {
            "jobId": job_id,
            "jobUrl": "https://example.com/apply",
            "companyName": "Acme",
            "roleTitle": "Engineer",
        }

        with session_scope() as db:
            first = create_application_draft(db, payload)
            second = create_application_draft(db, {**payload, "companyName": "Acme Inc"})
            assert first["id"] == second["id"]
            assert first["id"] == application_id_for_job(job_id)
            assert second["companyName"] == "Acme Inc"
            listed = [
                d for d in list_application_drafts(db, exclude_demo=False)
                if d.get("jobId") == job_id
            ]
            assert len(listed) == 1
            delete_application_draft(db, first["id"])

    def test_create_preserves_progress_fields(self):
        import uuid

        from app.db.store import session_scope
        from app.services.application_assistant.persistence import (
            create_application_draft,
            delete_application_draft,
            update_application_draft,
        )

        job_id = f"test_preserve_{uuid.uuid4().hex[:12]}"
        with session_scope() as db:
            draft = create_application_draft(db, {
                "jobId": job_id,
                "jobUrl": "https://example.com/apply",
                "companyName": "Acme",
                "roleTitle": "Engineer",
            })
            update_application_draft(db, draft["id"], {
                "status": "needs_review",
                "verifiedCount": 3,
                "fields": [{"id": "f1", "label": "Email"}],
            })
            again = create_application_draft(db, {
                "jobId": job_id,
                "jobUrl": "https://example.com/apply-new",
                "companyName": "Acme",
                "roleTitle": "Senior Engineer",
            })
            assert again["id"] == draft["id"]
            assert again["status"] == "needs_review"
            assert again["verifiedCount"] == 3
            assert len(again["fields"]) == 1
            assert again["roleTitle"] == "Senior Engineer"
            delete_application_draft(db, draft["id"])

    def test_cleanup_removes_duplicate_job_ids(self):
        import uuid

        from app.db.store import new_id, now_iso, session_scope, upsert_entity
        from app.services.application_assistant.persistence import (
            ENTITY_APPLICATION_DRAFT,
            cleanup_duplicate_application_drafts,
            delete_application_draft,
            list_application_drafts,
        )

        job_id = f"test_cleanup_{uuid.uuid4().hex[:12]}"
        base = {
            "jobId": job_id,
            "jobUrl": "https://careers.contoso.com/jobs/engineer",
            "companyName": "Contoso Labs",
            "roleTitle": "Engineer",
            "status": "ready_to_prepare",
            "fields": [],
            "verifiedCount": 0,
            "updatedAt": now_iso(),
            "createdAt": now_iso(),
        }

        with session_scope() as db:
            keeper_id = new_id("app_")
            dup_id = new_id("app_")
            upsert_entity(db, ENTITY_APPLICATION_DRAFT, {
                **base,
                "id": dup_id,
                "updatedAt": "2020-01-01T00:00:00Z",
            })
            upsert_entity(db, ENTITY_APPLICATION_DRAFT, {
                **base,
                "id": keeper_id,
                "status": "needs_review",
                "fields": [{"id": "f1"}],
                "verifiedCount": 2,
                "updatedAt": now_iso(),
            })
            removed = cleanup_duplicate_application_drafts(db)
            assert removed == 1
            listed = [d for d in list_application_drafts(db) if d.get("jobId") == job_id]
            assert len(listed) == 1
            assert listed[0]["id"] == keeper_id
            delete_application_draft(db, keeper_id)


class TestRuleBasedPrepFailureSummary:
    def test_ready_to_prepare_after_failed_prep(self):
        from app.services.application_assistant.qwen_agent import _rule_based_prep_failure_summary

        bundle = {"status": "ready_to_prepare", "agentRun": {"status": "failed"}}
        prep_result = {"success": False}
        summary = _rule_based_prep_failure_summary(bundle, prep_result)
        assert summary is not None
        assert "ready_to_prepare" in summary
        assert "no fix needed" not in summary.lower()

    def test_timeout_message(self):
        from app.services.application_assistant.qwen_agent import _rule_based_prep_failure_summary

        bundle = {"status": "ready_to_prepare", "stoppedReason": "Prep timeout after 600s"}
        prep_result = {"success": False, "error": "timeout"}
        summary = _rule_based_prep_failure_summary(bundle, prep_result)
        assert summary is not None
        assert "timed out" in summary.lower()
