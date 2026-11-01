"""Autopilot fills, checks and stages applications with deterministic code only.

Owner's rule (2026-11-01): no AI pass anywhere on the application path. The
pre-submission form check, the submission confirmation and the review-question
classifier must never create an LLM client, and the same input must always
give the same result.
"""

import asyncio
import inspect

import pytest

from app.services.application_assistant import error_normalizer as normalizer
from app.services.application_assistant import llm_client
from app.services.application_assistant import playwright_autopilot_executor as executor
from app.services.application_assistant import form_reviewer as reviewer


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    def _forbidden(*_a, **_k):
        raise AssertionError("an LLM client was created on the application path")

    monkeypatch.setattr(llm_client, "create_llm_client", _forbidden)
    for mod in (normalizer, reviewer, executor):
        if hasattr(mod, "create_llm_client"):
            monkeypatch.setattr(mod, "create_llm_client", _forbidden)


def _issue(label: str, **extra) -> dict:
    return {"gate": "SUBMIT_VALIDATION", "label": label, "issueType": "MISSING_REQUIRED",
            "reason": f"Required field '{label}' was rejected as empty on submit.", **extra}


def test_review_questions_are_classified_without_a_model():
    issues = [
        _issue("Will you require visa sponsorship?"),
        _issue("Gender"),
        _issue("Desired salary"),
        _issue("What pay range are you targeting?"),
        _issue("Are you able to work hybrid in our SF office?"),
        _issue("Earliest start date"),
    ]
    questions = asyncio.run(normalizer.build_pending_questions(issues))

    assert [(q["rawLabel"], q["category"]) for q in questions] == [
        ("Will you require visa sponsorship?", "WORK_AUTHORIZATION"),
        ("Gender", "DEMOGRAPHIC"),
        ("Desired salary", "COMPENSATION"),
        ("What pay range are you targeting?", "COMPENSATION"),
        ("Are you able to work hybrid in our SF office?", "ACKNOWLEDGMENT"),
        ("Earliest start date", "MISSING_FIELD"),
    ]
    # The question is the field's own label, so the saved answer keys back to it.
    assert all(q["question"] == q["rawLabel"] for q in questions)


def test_issues_a_candidate_cannot_answer_do_not_become_questions():
    issues = [
        {"gate": "DOM_VERIFY", "label": "Location", "issueType": "MISMATCH",
         "reason": "Location 'Austin' doesn't match the candidate's actual profile city/state."},
        {"gate": "SUBMIT", "label": "", "reason": "This job is no longer accepting applications"},
        {"gate": "REQUIRED_FIELDS_CHECK", "label": "3 fields", "reason": "3 required fields unfilled"},
    ]
    assert asyncio.run(normalizer.build_pending_questions(issues)) == []
    assert normalizer.classify_review_issue(issues[0]["reason"], label="Location", issue_type="MISMATCH")[
        "category"] == "AUTOFILL_MISMATCH"
    assert normalizer.classify_review_issue(issues[1]["reason"])["category"] == "JOB_EXPIRED"


def test_a_label_is_read_back_out_of_a_raw_reason():
    # Jobs staged before field metadata existed carry only the raw text.
    questions = asyncio.run(normalizer.build_pending_questions(
        [{"reason": "Required field 'Do you need sponsorship?' was rejected as empty on submit."}]
    ))
    assert questions[0]["rawLabel"] == "Do you need sponsorship?"
    assert questions[0]["category"] == "WORK_AUTHORIZATION"


def test_classification_is_stable_across_runs():
    issue = _issue("Pronouns")
    first = asyncio.run(normalizer.build_pending_questions([issue]))
    second = asyncio.run(normalizer.build_pending_questions([dict(issue)]))
    assert first == second


def test_pre_submission_check_runs_without_a_model():
    form = [
        {"id": "first_name", "label": "First Name *", "value": "Ada", "required": True},
        {"id": "q_auth", "label": "Are you authorized to work in the US? *", "value": "", "required": True},
        {"id": "cover", "label": "Cover letter (optional)", "value": ""},
    ]
    res = asyncio.run(reviewer.review_and_heal_form_state(
        form_state=form, validation_errors=[], profile={}, company="Acme", title="Engineer",
    ))
    assert res["readyToSubmit"] is False
    assert [f["fieldId"] for f in res["missingOrInvalidFields"]] == ["q_auth"]


def test_submission_confirmation_runs_without_a_model():
    res = asyncio.run(reviewer.verify_submission_confirmation(
        body_text="Thank you for applying to Acme!", confirmation_url="https://jobs.acme.com/thanks",
        active_errors=[], company="Acme", title="Engineer",
    ))
    assert res["submissionConfirmed"] is True


def test_the_fill_path_has_no_ai_essay_writer():
    source = inspect.getsource(executor)
    assert "llm_answer_generator" not in source
    assert "generate_theory_answer" not in source
    assert not hasattr(executor, "AI_WRITTEN_ESSAYS_ENABLED")
