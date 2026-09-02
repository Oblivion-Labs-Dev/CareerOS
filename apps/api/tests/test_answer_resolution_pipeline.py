"""Regression tests for the answer resolution pipeline.

Tests every confirmed bug (A-J) to ensure they never recur.
Tests the question classifier, profile answer resolver, and cross-field validator.
"""

import pytest
from app.services.application_assistant.question_classifier import (
    QuestionType,
    classify_question,
    classify_free_text_intent,
    is_sensitive_factual,
)
from app.services.application_assistant.profile_answer_resolver import (
    resolve_answer,
    AnswerResolution,
)
from app.services.application_assistant.cross_field_validator import (
    validate_answers,
    ValidationReport,
)


# ── Test Profile ──────────────────────────────────────────────────────────────

PROFILE = {
    "firstName": "Akshay",
    "lastName": "Borse",
    "fullName": "Akshay Borse",
    "email": "amsborse@gmail.com",
    "phone": "(425) 336-9852",
    "location": "Auburn, WA",
    "city": "Auburn",
    "state": "Washington",
    "linkedin": "https://www.linkedin.com/in/amsborse/",
    "github": "https://github.com/amsborse",
    "portfolio": "https://amsborse.github.io/resume",
    "workAuthorization": "Yes",
    "sponsorship": "Yes",
    "yearsExperience": "7",
    "currentTitle": "Senior Software Engineer",
    "currentCompany": "Microsoft",
    "gender": "Male",
    "raceEthnicity": "Asian",
    "hispanic": "No",
    "veteran": "I am not a protected veteran",
    "disability": "No, I don't have a disability",
    "transgender": "No",
    "sexualOrientation": "Heterosexual",
    "phoneCountryCode": "+1",
    "jobDiscoveryDefault": "LinkedIn",
    "workAuth": {
        "authorizedToWorkInUS": True,
        "authorizationType": "H1B",
        "requiresSponsorshipNowOrFuture": True,
        "permanentWorkAuthorization": False,
        "usCitizen": False,
        "usNational": False,
        "greenCardHolder": False,
    },
    "security": {
        "hasHeldUSSecurityClearance": False,
        "eligibleForUSSecurityClearance": False,
    },
}


# ── Question Classifier Tests ─────────────────────────────────────────────────

class TestQuestionClassifier:
    """Tests that questions are classified into the correct semantic types."""

    def test_sponsorship_classified(self):
        assert classify_question("Will you require sponsorship?") == QuestionType.SPONSORSHIP_REQUIRED

    def test_visa_sponsorship_classified(self):
        assert classify_question("Will you now or in the future require visa sponsorship?") == QuestionType.SPONSORSHIP_REQUIRED

    def test_work_authorized_classified(self):
        assert classify_question("Are you authorized to work in the U.S.?") == QuestionType.WORK_AUTHORIZED

    def test_permanent_auth_vs_work_auth(self):
        """BUG B: permanent authorization must be classified differently from work authorization."""
        assert classify_question("Do you have permanent authorization to work in the US?") == QuestionType.PERMANENT_WORK_AUTHORIZATION
        assert classify_question("Are you authorized to work in the US?") == QuestionType.WORK_AUTHORIZED

    def test_export_control_classified(self):
        assert classify_question("EXPORT CONTROLS - This position requires access to export-controlled items") == QuestionType.EXPORT_CONTROL

    def test_clearance_eligibility_classified(self):
        assert classify_question("CLEARANCE ELIGIBILITY - Are you eligible to obtain a U.S. security clearance?") == QuestionType.SECURITY_CLEARANCE_ELIGIBILITY

    def test_hispanic_vs_race(self):
        """BUG G: Hispanic/Latino question must be classified as ethnicity, NOT race."""
        assert classify_question("Are you Hispanic/Latino?") == QuestionType.ETHNICITY_HISPANIC_LATINO
        assert classify_question("What is your race?") == QuestionType.RACE
        assert classify_question("Please identify your racial/ethnic background") == QuestionType.RACE

    def test_gender_classified(self):
        assert classify_question("Gender") == QuestionType.GENDER

    def test_state_classified(self):
        assert classify_question("Please select the state in which you reside") == QuestionType.STATE

    def test_how_heard_classified(self):
        assert classify_question("How did you hear about us?") == QuestionType.HOW_HEARD

    def test_sensitive_factual_types(self):
        """All sensitive factual types must block LLM generation."""
        assert is_sensitive_factual(QuestionType.SPONSORSHIP_REQUIRED)
        assert is_sensitive_factual(QuestionType.WORK_AUTHORIZED)
        assert is_sensitive_factual(QuestionType.PERMANENT_WORK_AUTHORIZATION)
        assert is_sensitive_factual(QuestionType.EXPORT_CONTROL)
        assert is_sensitive_factual(QuestionType.CITIZENSHIP)
        assert is_sensitive_factual(QuestionType.SECURITY_CLEARANCE_ELIGIBILITY)
        assert is_sensitive_factual(QuestionType.GENDER)
        assert is_sensitive_factual(QuestionType.ETHNICITY_HISPANIC_LATINO)
        assert is_sensitive_factual(QuestionType.RACE)

    def test_free_text_blog_classified(self):
        qtype = classify_free_text_intent("Share a recent blog post you've read")
        assert qtype == QuestionType.FREE_TEXT_BLOG_POST


# ── Profile Answer Resolver Tests ─────────────────────────────────────────────

class TestProfileAnswerResolver:
    """Tests that every confirmed bug is fixed by the centralized resolver."""

    # ── Bug A: Sponsorship ──
    def test_h1b_sponsorship_yes(self):
        """BUG FIX A: H1B candidate must answer 'Yes' to sponsorship."""
        res = resolve_answer("Will you require sponsorship?", PROFILE, ["Yes", "No"])
        assert res.answer == "Yes"
        assert res.confidence == 1.0
        assert res.resolution_method == "PROFILE_OPTION_MAPPING"

    def test_h1b_sponsorship_future(self):
        res = resolve_answer("Will you now or in the future require visa sponsorship?", PROFILE, ["Yes", "No"])
        assert res.answer == "Yes"

    # ── Bug B: Permanent Authorization ──
    def test_h1b_permanent_auth_no(self):
        """BUG FIX B: H1B holder does NOT have permanent authorization."""
        res = resolve_answer("Do you have permanent authorization to work in the US?", PROFILE, ["Yes", "No"])
        assert res.answer == "No"
        assert res.confidence == 1.0

    def test_h1b_authorized_yes(self):
        """H1B holder IS authorized to work (just not permanently)."""
        res = resolve_answer("Are you authorized to work in the U.S.?", PROFILE, ["Yes", "No"])
        assert res.answer == "Yes"

    # ── Bug C: Export Controls ──
    def test_h1b_export_control_none(self):
        """BUG FIX C: H1B holder is NOT a US citizen/national for export control."""
        res = resolve_answer(
            "EXPORT CONTROLS - Which of the following describes your status?",
            PROFILE,
            ["A United States citizen or national", "A lawful permanent resident", "None of the above"],
        )
        assert res.answer == "None of the above"
        assert "citizen" not in (res.answer or "").lower()

    def test_export_control_never_selects_citizen_for_h1b(self):
        """Never select citizen option when not a citizen."""
        res = resolve_answer(
            "Export control classification",
            PROFILE,
            ["U.S. Citizen", "Permanent Resident", "None of the above", "Other"],
        )
        assert "citizen" not in (res.answer or "").lower()

    # ── Bug D: Security Clearance ──
    def test_clearance_eligibility_no(self):
        """BUG FIX D: Must use profile fact, not resume keywords."""
        res = resolve_answer("Are you eligible for a U.S. security clearance?", PROFILE, ["Yes", "No"])
        assert res.answer == "No"

    def test_clearance_level_none(self):
        res = resolve_answer("What level of clearance have you held?", PROFILE, ["Secret", "Top Secret", "None", "N/A"])
        assert res.answer in ("None", "N/A")

    # ── Bug E: Location ──
    def test_location_from_profile(self):
        """BUG FIX E: Location must come from profile, never from first name."""
        res = resolve_answer("Location (City)", PROFILE)
        assert "Auburn" in (res.answer or "")
        assert "akshay" not in (res.answer or "").lower()

    def test_akshay_never_becomes_location(self):
        """First name must never be used as location."""
        res = resolve_answer("City", PROFILE)
        assert res.answer != "Akshay"
        assert res.answer != "akshay"

    # ── Bug F: Phone ──
    def test_phone_is_full_number(self):
        """BUG FIX F: Phone field must have actual digits, not just country code."""
        res = resolve_answer("Phone", PROFILE)
        assert res.answer == "(425) 336-9852"

    # ── Bug G: Hispanic / Race ──
    def test_hispanic_question_answer_no(self):
        """BUG FIX G: Hispanic question must answer 'No', not a race option."""
        res = resolve_answer(
            "Are you Hispanic/Latino?",
            PROFILE,
            ["Yes", "No", "American Indian or Alaskan Native", "Asian", "Black or African American"],
        )
        assert res.answer == "No"
        # Must NEVER select a race option for an ethnicity question
        assert "indian" not in (res.answer or "").lower()
        assert "asian" not in (res.answer or "").lower()

    def test_race_question_answer_asian(self):
        res = resolve_answer("What is your race?", PROFILE, ["Asian", "White", "Black", "Hispanic or Latino"])
        assert res.answer == "Asian"
        # Must NEVER select an ethnicity option for a race question
        assert "hispanic" not in (res.answer or "").lower()

    # ── Bug H: State ──
    def test_state_washington(self):
        """BUG FIX H: State must be Washington, not Illinois or random."""
        res = resolve_answer(
            "Please select the state in which you reside",
            PROFILE,
            ["California", "Illinois", "New York", "Washington", "Texas"],
        )
        assert res.answer == "Washington"

    def test_state_no_fallback_to_random(self):
        """Even if Washington not in options, must not pick random."""
        res = resolve_answer("Current state", PROFILE, ["Alabama", "Alaska", "Arizona"])
        # Should still try to match "Washington" — won't find exact but should set from profile
        assert res.profile_key == "state"

    # ── Bug I: Gender ──
    def test_gender_male(self):
        """BUG FIX I: Gender must come from profile ('Male'), not 'Decline'."""
        res = resolve_answer("Gender", PROFILE, ["Male", "Female", "Non-binary", "Decline To Self Identify"])
        assert res.answer == "Male"

    # ── Bug J: How Did You Hear ──
    def test_how_heard_linkedin(self):
        """BUG FIX J: Must use profile.jobDiscoveryDefault, not random."""
        res = resolve_answer("How did you hear about us?", PROFILE, ["LinkedIn", "Indeed", "Referral", "Other"])
        assert res.answer == "LinkedIn"

    def test_how_heard_fallback_to_other(self):
        res = resolve_answer("How did you hear about us?", PROFILE, ["Indeed", "Referral", "Other"])
        assert res.answer == "Other"


# ── Cross-Field Validator Tests ───────────────────────────────────────────────

class TestCrossFieldValidator:
    """Tests that contradictory answers are caught and blocked."""

    def test_h1b_sponsorship_no_blocked(self):
        """H1B candidate saying no to sponsorship must be BLOCKED."""
        resolutions = [
            AnswerResolution(
                field_id="sponsorship",
                question="Will you require sponsorship?",
                question_type=QuestionType.SPONSORSHIP_REQUIRED.value,
                answer="No",
                resolution_method="PROFILE_EXACT",
                confidence=1.0,
            ),
        ]
        report = validate_answers(resolutions, PROFILE)
        assert report.status == "FAIL"
        assert any("SPONSORSHIP" in e.rule for e in report.blocking_errors)

    def test_us_citizen_false_export_citizen_blocked(self):
        """Non-citizen selecting 'US citizen' for export control must be BLOCKED."""
        resolutions = [
            AnswerResolution(
                field_id="export",
                question="Export control classification",
                question_type=QuestionType.EXPORT_CONTROL.value,
                answer="A United States citizen or national",
                resolution_method="PROFILE_OPTION_MAPPING",
                confidence=1.0,
            ),
        ]
        report = validate_answers(resolutions, PROFILE)
        assert report.status == "FAIL"
        assert any("EXPORT" in e.rule or "CITIZENSHIP" in e.rule for e in report.blocking_errors)

    def test_state_mismatch_blocked(self):
        """Profile state WA but answer Illinois must be BLOCKED."""
        resolutions = [
            AnswerResolution(
                field_id="state",
                question="Select your state",
                question_type=QuestionType.STATE.value,
                answer="Illinois",
                resolution_method="PROFILE_OPTION_MAPPING",
                confidence=1.0,
            ),
        ]
        report = validate_answers(resolutions, PROFILE)
        assert report.status == "FAIL"
        assert any("STATE" in e.rule for e in report.blocking_errors)

    def test_ethnicity_race_crossover_blocked(self):
        """Race option on ethnicity question must be BLOCKED."""
        resolutions = [
            AnswerResolution(
                field_id="hispanic",
                question="Are you Hispanic/Latino?",
                question_type=QuestionType.ETHNICITY_HISPANIC_LATINO.value,
                answer="American Indian or Alaskan Native",
                resolution_method="PROFILE_OPTION_MAPPING",
                confidence=1.0,
            ),
        ]
        report = validate_answers(resolutions, PROFILE)
        assert report.status == "FAIL"
        assert any("CROSSOVER" in e.rule for e in report.blocking_errors)

    def test_phone_country_code_only_blocked(self):
        """Phone field with only country code (no actual digits) must be BLOCKED."""
        resolutions = [
            AnswerResolution(
                field_id="phone",
                question="Phone",
                question_type=QuestionType.PHONE.value,
                answer="United States +1",
                resolution_method="PROFILE_EXACT",
                confidence=1.0,
            ),
        ]
        report = validate_answers(resolutions, PROFILE)
        assert report.status == "FAIL"
        assert any("PHONE" in e.rule for e in report.blocking_errors)

    def test_clearance_yes_when_ineligible_blocked(self):
        """Saying yes to clearance when profile says not eligible must be BLOCKED."""
        resolutions = [
            AnswerResolution(
                field_id="clearance",
                question="Are you eligible for security clearance?",
                question_type=QuestionType.SECURITY_CLEARANCE_ELIGIBILITY.value,
                answer="Yes",
                resolution_method="PROFILE_EXACT",
                confidence=1.0,
            ),
        ]
        report = validate_answers(resolutions, PROFILE)
        assert report.status == "FAIL"
        assert any("CLEARANCE" in e.rule for e in report.blocking_errors)

    def test_name_as_location_blocked(self):
        """Candidate's first name used as location must be BLOCKED."""
        resolutions = [
            AnswerResolution(
                field_id="location",
                question="City",
                question_type=QuestionType.LOCATION.value,
                answer="Akshay",
                resolution_method="PROFILE_EXACT",
                confidence=1.0,
            ),
        ]
        report = validate_answers(resolutions, PROFILE)
        assert report.status == "FAIL"
        assert any("NAME_AS_LOCATION" in e.rule for e in report.blocking_errors)

    def test_llm_generated_sensitive_blocked(self):
        """LLM-generated answer for sensitive field must be BLOCKED."""
        resolutions = [
            AnswerResolution(
                field_id="gender",
                question="Gender",
                question_type=QuestionType.GENDER.value,
                answer="Female",
                resolution_method="LLM_GENERATED_TEXT",
                confidence=0.95,
            ),
        ]
        report = validate_answers(resolutions, PROFILE)
        assert report.status == "FAIL"
        assert any("SENSITIVE_LLM" in e.rule for e in report.blocking_errors)

    def test_correct_answers_pass(self):
        """All correct answers should pass validation."""
        resolutions = [
            AnswerResolution(
                field_id="sponsorship",
                question="Will you require sponsorship?",
                question_type=QuestionType.SPONSORSHIP_REQUIRED.value,
                answer="Yes",
                resolution_method="PROFILE_EXACT",
                confidence=1.0,
            ),
            AnswerResolution(
                field_id="state",
                question="Select your state",
                question_type=QuestionType.STATE.value,
                answer="Washington",
                resolution_method="PROFILE_OPTION_MAPPING",
                confidence=1.0,
            ),
            AnswerResolution(
                field_id="gender",
                question="Gender",
                question_type=QuestionType.GENDER.value,
                answer="Male",
                resolution_method="PROFILE_OPTION_MAPPING",
                confidence=1.0,
            ),
        ]
        report = validate_answers(resolutions, PROFILE)
        assert report.status == "PASS"
        assert len(report.blocking_errors) == 0

    def test_permanent_auth_yes_when_h1b_blocked(self):
        resolutions = [
            AnswerResolution(
                field_id="perm_auth",
                question="Do you have permanent work authorization?",
                question_type=QuestionType.PERMANENT_WORK_AUTHORIZATION.value,
                answer="Yes",
                resolution_method="PROFILE_EXACT",
                confidence=1.0,
            ),
        ]
        report = validate_answers(resolutions, PROFILE)
        assert report.status == "FAIL"
        assert any("PERMANENT" in e.rule for e in report.blocking_errors)


# ── Submission Policy Tests (Verified Autonomy) ──────────────────────────────

from app.services.application_assistant.submission_policy import (
    SubmissionPolicy,
    SubmissionDecision,
)
from app.services.application_assistant.browser_verifier import (
    DOMVerificationResult,
    DOMVerificationIssue,
)


class TestSubmissionPolicy:
    """Tests that deterministic policy decides whether submission is permitted."""

    def test_clean_validated_application_ready_to_submit(self):
        resolutions = [
            AnswerResolution(
                field_id="first_name",
                question="First Name",
                question_type=QuestionType.FIRST_NAME.value,
                answer="Akshay",
                resolution_method="PROFILE_EXACT",
                confidence=1.0,
            ),
            AnswerResolution(
                field_id="sponsorship",
                question="Will you require sponsorship?",
                question_type=QuestionType.SPONSORSHIP_REQUIRED.value,
                answer="Yes",
                resolution_method="PROFILE_EXACT",
                confidence=1.0,
            ),
        ]
        validation_report = validate_answers(resolutions, PROFILE)
        dom_verification = DOMVerificationResult(passed=True)

        eval_res = SubmissionPolicy.evaluate(
            resolutions=resolutions,
            validation_report=validation_report,
            dom_verification=dom_verification,
            profile=PROFILE,
        )
        assert eval_res.decision == SubmissionDecision.READY_TO_SUBMIT
        assert eval_res.can_auto_submit is True
        assert len(eval_res.blocking_issues) == 0

    def test_validation_failure_routes_to_needs_review(self):
        """Cross-field validation failure must route to NEEDS_REVIEW."""
        resolutions = [
            AnswerResolution(
                field_id="sponsorship",
                question="Will you require sponsorship?",
                question_type=QuestionType.SPONSORSHIP_REQUIRED.value,
                answer="No",
                resolution_method="PROFILE_EXACT",
                confidence=1.0,
            ),
        ]
        validation_report = validate_answers(resolutions, PROFILE)
        eval_res = SubmissionPolicy.evaluate(
            resolutions=resolutions,
            validation_report=validation_report,
            profile=PROFILE,
        )
        assert eval_res.decision == SubmissionDecision.NEEDS_REVIEW
        assert eval_res.can_auto_submit is False
        assert any(issue["gate"] == "CROSS_FIELD_VALIDATION" for issue in eval_res.blocking_issues)

    def test_dom_mismatch_routes_to_needs_review(self):
        """Live DOM value mismatch (e.g. Auburn ND in browser) must route to NEEDS_REVIEW."""
        resolutions = [
            AnswerResolution(
                field_id="loc",
                question="Location (City)",
                question_type=QuestionType.LOCATION.value,
                answer="Auburn, WA",
                resolution_method="PROFILE_EXACT",
                confidence=1.0,
            ),
        ]
        validation_report = validate_answers(resolutions, PROFILE)
        dom_verification = DOMVerificationResult(
            passed=False,
            issues=[
                DOMVerificationIssue(
                    field_id="loc",
                    label="Location",
                    intended_value="Auburn, WA",
                    actual_dom_value="Auburn, ND",
                    issue_type="MISMATCH",
                    severity="BLOCKING",
                    details="Location has wrong state (ND instead of WA)",
                )
            ]
        )
        eval_res = SubmissionPolicy.evaluate(
            resolutions=resolutions,
            validation_report=validation_report,
            dom_verification=dom_verification,
            profile=PROFILE,
        )
        assert eval_res.decision == SubmissionDecision.NEEDS_REVIEW
        assert eval_res.can_auto_submit is False
        assert any(issue["gate"] == "DOM_READBACK_VERIFIER" for issue in eval_res.blocking_issues)

    def test_missing_required_dom_field_routes_to_needs_review(self):
        resolutions = []
        validation_report = ValidationReport(status="PASS")
        dom_verification = DOMVerificationResult(
            passed=False,
            unresolved_required_fields=["Phone Number", "Work Authorization"],
        )
        eval_res = SubmissionPolicy.evaluate(
            resolutions=resolutions,
            validation_report=validation_report,
            dom_verification=dom_verification,
            profile=PROFILE,
        )
        assert eval_res.decision == SubmissionDecision.NEEDS_REVIEW
        assert eval_res.can_auto_submit is False
        assert any(issue["gate"] == "REQUIRED_FIELDS_CHECK" for issue in eval_res.blocking_issues)

    def test_critical_fact_llm_generated_routes_to_needs_review(self):
        """LLM-generated answer for citizenship must be BLOCKED from auto-submission."""
        resolutions = [
            AnswerResolution(
                field_id="cit",
                question="Are you a US citizen?",
                question_type=QuestionType.CITIZENSHIP.value,
                answer="Yes",
                resolution_method="LLM_GENERATED_TEXT",
                confidence=0.99,
            ),
        ]
        validation_report = validate_answers(resolutions, PROFILE)
        eval_res = SubmissionPolicy.evaluate(
            resolutions=resolutions,
            validation_report=validation_report,
            profile=PROFILE,
        )
        assert eval_res.decision == SubmissionDecision.NEEDS_REVIEW
        assert eval_res.can_auto_submit is False
        assert any(issue["gate"] == "CRITICAL_FACT_PROVENANCE" for issue in eval_res.blocking_issues)

