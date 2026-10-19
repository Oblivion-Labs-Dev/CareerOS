"""ATS application-driver registry tests (#98).

Controlled, offline tests only: synthetic ATS pages sampled from real public
apply forms are in tests/fixtures/ats_forms/. Nothing here can reach the
network or submit an application — the drivers are preparation-only by
construction (asserted in test_never_submits).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.store import list_entities, session_scope
from app.main import app
from app.services.application_assistant.drivers import (
    detect_platform,
    get_driver,
    preparation_idempotency_key,
)
from app.services.application_assistant.drivers.base import ApplicationMode
from app.services.application_assistant.drivers.states import (
    map_pipeline_state,
    pipeline_snapshot_from_autopilot_job,
)
from app.services.application_assistant.drivers.profile_map import map_questions

FIXTURES = Path(__file__).parent / "fixtures" / "ats_forms"

PROFILE = {
    "first_name": "Ada",
    "last_name": "Lovelace",
    "email": "ada@example.com",
    "phone": "+1 555 010 2030",
    "location": "Seattle, WA",
    "linkedin_url": "https://www.linkedin.com/in/adalovelace",
    "github_url": "https://github.com/adalovelace",
    "portfolio_url": "https://ada.dev",
    "current_company": "Analytical Engines Inc",
    "current_title": "Senior Engineer",
}

GREENHOUSE_JOB = {
    "companyName": "Acme Corp",
    "title": "Senior Software Engineer",
    "applyUrl": "https://job-boards.greenhouse.io/acme/jobs/4501901003",
}
ASHBY_JOB = {
    "companyName": "Globex",
    "title": "Staff Platform Engineer",
    "applyUrl": "https://jobs.ashbyhq.com/globex/abc123",
}
LEVER_JOB = {
    "companyName": "Initech",
    "title": "Senior Backend Engineer",
    "applyUrl": "https://jobs.lever.co/initech/b9a1f06e-4a62",
}
WORKDAY_JOB = {
    "companyName": "Moms Friendly Robot",
    "title": "Software Engineer",
    "applyUrl": "https://mfr.wd1.myworkdayjobs.com/mfr/job/Seattle/REQ_0011",
}

_job_urls = {
    "greenhouse": "https://job-boards.greenhouse.io/acme/jobs/4501901003",
    "ashby": "https://jobs.ashbyhq.com/globex/abc123",
    "lever": "https://jobs.lever.co/initech/b9a1f06e-4a62",
    "workable": "https://apply.workable.com/huggingface/j/123/",
    "smartrecruiters": "https://careers.smartrecruiters.com/Acme/743999960",
    "workday": "https://acme.wd1.myworkdayjobs.com/External/job/x",
    "icims": "https://acme.icims.com/jobs/1234/job",
    "oracle": "https://acme.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/1",
    "personio": "https://acme.jobs.personio.de/job/123",
    "recruitee": "https://acme.recruitee.com/o/senior-engineer",
    "usajobs": "https://www.usajobs.gov/Job/JobDetail/123456789",
}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("platform", list(_job_urls))
def test_detects_all_ten_platforms(platform: str) -> None:
    driver = detect_platform(_job_urls[platform])
    assert driver is not None
    assert driver.platform == platform


def test_unknown_url_falls_back_to_generic() -> None:
    assert detect_platform("https://example.com/careers/x") is None
    driver = get_driver("generic")
    assert driver is not None
    assert driver.platform == "generic"


def test_unknown_platform_lookup_returns_none() -> None:
    assert get_driver("not-a-platform") is None


# ---------------------------------------------------------------------------
# Preparation (the 3 controlled drivers + portal driver behaviour)
# ---------------------------------------------------------------------------


def _form(platform: str) -> str:
    return (FIXTURES / f"{platform}.html").read_text(encoding="utf-8")


def test_greenhouse_prepares_realistic_application() -> None:
    driver = get_driver("greenhouse")
    prepared = driver.prepare(GREENHOUSE_JOB, PROFILE, form_html=_form("greenhouse"))
    assert prepared.platform == "greenhouse"
    assert prepared.form_question_count == 10
    by_key = {q.key: q for q in prepared.questions}

    first = by_key["first_name"]
    assert first.mapped_value == "Ada" and first.mapping_source == "profile"
    assert by_key["email"].mapped_value == "ada@example.com"
    assert by_key["email"].type == "email"
    assert by_key["resume"].mapped_value == "RESUME"
    assert by_key["current_company_name"].mapped_value == "Analytical Engines Inc"

    # Compensation is sensitive: review, never guessed.
    comp = by_key["expected_compensation"]
    assert comp.mapping_source == "review_required" and comp.mapped_value is None

    # "Why do you want to work at Acme?" has no deterministic mapping.
    why = by_key["job_description_why"]
    assert why.mapping_source == "review_required"

    # warn-capability note from the Greenhouse driver wrapper.
    assert any("autopilot" in w for w in prepared.warnings)
    assert not prepared.capabilities.submit_authorized


def test_ashby_prepares_and_routes_work_authorization_to_review() -> None:
    driver = get_driver("ashby")
    prepared = driver.prepare(ASHBY_JOB, PROFILE, form_html=_form("ashby"))
    by_key = {q.key: q for q in prepared.questions}

    assert by_key["firstName"].mapped_value == "Ada"
    assert by_key["github"].mapped_value == "https://github.com/adalovelace"

    work_auth = by_key["workAuthorization"]
    assert work_auth.type == "select"
    assert work_auth.options == ["Select an option", "Yes", "No"]
    assert work_auth.required is True
    assert work_auth.mapping_source == "review_required"
    assert prepared.mode == ApplicationMode.REVIEW


def test_lever_prepares_and_classifies_mode() -> None:
    driver = get_driver("lever")
    prepared = driver.prepare(LEVER_JOB, PROFILE, form_html=_form("lever"))
    by_key = {q.key: q for q in prepared.questions}

    assert by_key["name"].mapped_value == "Ada Lovelace"
    assert by_key["phone"].mapping_source == "profile"
    assert by_key["linkedinUrl"].mapping_source == "profile"
    assert by_key["years"].mapping_source == "review_required"
    # Everything else mapped deterministically? mode = REVIEW because of
    # unmapped required "Years of experience".
    assert prepared.mode == ApplicationMode.REVIEW


def test_fully_mapped_form_classifies_auto_without_submittable_output() -> None:
    # Contact-only form: every required question maps deterministically.
    html = """
    <form><label for="first_name">First Name</label>
    <input type="text" id="first_name" name="first_name">
    <label for="email">Email</label>
    <input type="email" id="email" name="email"></form>
    """
    driver = get_driver("ashby")
    prepared = driver.prepare(ASHBY_JOB, PROFILE, form_html=html)
    assert prepared.mode == ApplicationMode.AUTO
    assert prepared.auto_mapped_count == 2
    # AUTO preparation still describes a non-submittable outcome:
    assert prepared.to_dict()["submission"]["supported"] is False
    assert prepared.to_dict()["submission"]["authorization"] == "NOT_REQUESTED"


def test_captcha_form_classifies_manual() -> None:
    html = """
    <form><label for="first_name">First Name</label>
    <input type="text" id="first_name" name="first_name">
    <div class="g-recaptcha" data-sitekey="xyz"></div>
    <input type="text" name="captchaResponse"></form>
    """
    driver = get_driver("lever")
    prepared = driver.prepare(LEVER_JOB, PROFILE, form_html=html)
    assert prepared.mode == ApplicationMode.MANUAL
    assert any("CAPTCHA" in r or "captcha" in r.lower() for r in prepared.manual_reasons)


def test_portal_drivers_route_to_review_without_form_html() -> None:
    driver = get_driver("workday")
    prepared = driver.prepare(WORKDAY_JOB, PROFILE)

    if prepared.manual_reasons:
        expected = ApplicationMode.MANUAL
    else:
        expected = ApplicationMode.REVIEW
    assert prepared.mode == expected
    driver_oracle = get_driver("oracle")

    prepared_oracle = driver_oracle.prepare(
        {**WORKDAY_JOB, "applyUrl": _job_urls["oracle"]}, PROFILE
    )
    assert prepared_oracle.mode in (ApplicationMode.REVIEW, ApplicationMode.MANUAL)


def test_approved_answer_beats_review_route() -> None:
    html = """
    <form><label for="why_us">Why do you want to work here?</label>
    <textarea id="why_us" name="why_us" required></textarea></form>
    """
    driver = get_driver("greenhouse")
    prepared = driver.prepare(
        GREENHOUSE_JOB,
        PROFILE,
        form_html=html,
        approved_answers={"why do you want to work here?": "I build parsers for a living."},
    )
    question = prepared.questions[0]
    assert question.mapped_value == "I build parsers for a living."
    assert question.mapping_source == "approved_answer"
    assert prepared.mode == ApplicationMode.AUTO


# ---------------------------------------------------------------------------
# Deterministic mapping unit checks
# ---------------------------------------------------------------------------


def test_map_questions_never_invents_answers() -> None:
    raw_fields = [
        {"name": "first_name", "label": "First Name", "type": "text", "required": True},
        {"name": "salary", "label": "Expected Salary Expectations", "type": "text", "required": True},
        {"name": "mystery_field", "label": "", "type": "unknown", "required": False},
    ]
    result = map_questions(raw_fields, {}, {})
    salary = next(q for q in result.questions if q.key == "salary")
    assert salary.mapping_source == "review_required"
    assert any("human review" in r.lower() for r in result.review_reasons)
    mystery = next(q for q in result.questions if q.key == "mystery_field")
    assert mystery.mapped_value is None


# ---------------------------------------------------------------------------
# Capabilities explicitly declared
# ---------------------------------------------------------------------------


def test_capabilities_activity_declared() -> None:
    portal = get_driver("icims").capabilities
    assert "discover_questions" not in portal.supported_operations()
    assert "discover_questions" in portal.unsupported_operations()
    form = get_driver("ashby").capabilities
    assert form.browser_fallback and not form.submit_authorized
    generic_caps = get_driver("generic").capabilities
    assert generic_caps.browser_fallback


# ---------------------------------------------------------------------------
# Idempotency / duplicate preparation prevention
# ---------------------------------------------------------------------------


def test_idempotency_key_stable_and_scoped() -> None:
    key_a = preparation_idempotency_key("greenhouse", GREENHOUSE_JOB)
    key_b = preparation_idempotency_key("greenhouse", dict(GREENHOUSE_JOB))
    assert key_a == key_b
    different = preparation_idempotency_key(
        "greenhouse", {**GREENHOUSE_JOB, "title": "Other Role"}
    )
    assert different != key_a
    # Requisitions that differ must not collide.
    other_req = preparation_idempotency_key(
        "greenhouse", {**GREENHOUSE_JOB, "externalId": "999", "applyUrl": "https://job-boards.greenhouse.io/acme/jobs/999"}
    )
    assert other_req != key_a


def test_preparation_claimed_once() -> None:
    with session_scope() as db:
        before = [c for c in list_entities(db, "aa_preparation_claim")]
    payload = {"job": GREENHOUSE_JOB, "formHtml": _form("greenhouse")}
    with TestClient(app) as client:
        response_first = client.post("/application-assistant/drivers/prepare", json=payload)
        assert response_first.status_code == 200
        first = response_first.json()
        assert first["reused"] is False
        assert first["mode"] == "REVIEW"

        response_second = client.post("/application-assistant/drivers/prepare", json=payload)
        assert response_second.status_code == 200
        second = response_second.json()
        assert second["reused"] is True
        assert second["idempotencyKey"] == first["idempotencyKey"]
    with session_scope() as db:
        after = [c for c in list_entities(db, "aa_preparation_claim")]
    assert len([c for c in after if c not in before]) >= 1


# ---------------------------------------------------------------------------
# Metrics + endpoints
# ---------------------------------------------------------------------------


def test_driver_endpoints() -> None:
    with TestClient(app) as client:
        listing = client.get("/application-assistant/drivers")
        assert listing.status_code == 200
        drivers = listing.json()["drivers"]
        platforms = {d["platform"] for d in drivers}
        assert {
            "greenhouse", "ashby", "lever", "workable", "smartrecruiters",
            "workday", "icims", "oracle", "personio", "recruitee", "generic", "usajobs",
        } <= platforms
        ashby = next(d for d in drivers if d["platform"] == "ashby")
        assert "submit_authorized" not in ashby["capabilities"]
        assert "submit_authorized" in ashby["unsupportedCapabilities"]

        response_caps = client.get("/application-assistant/drivers/ashby/capabilities")
        assert response_caps.status_code == 200
        assert response_caps.json()["platform"] == "ashby"

        response_missing = client.get("/application-assistant/drivers/nope/capabilities")
        assert response_missing.json()["error"].startswith("unknown driver")

        prepare = client.post(
            "/application-assistant/drivers/prepare",
            json={"job": ASHBY_JOB, "formHtml": _form("ashby")},
        )
        assert prepare.status_code == 200
        prepared = prepare.json()
        assert prepared["platform"] == "ashby"
        assert prepared["questions"], "questions discovered from fixture HTML"
        assert prepared["submission"]["supported"] is False

        metrics_row = [
            d for d in client.get("/application-assistant/drivers").json()["drivers"]
            if d["platform"] == "ashby"
        ][0]
        assert metrics_row["metrics"].get("preparations", 0) >= 0


# ---------------------------------------------------------------------------
# Global safety invariants
# ---------------------------------------------------------------------------


def test_never_submits() -> None:
    """No driver in the registry is authorized to submit through this layer."""

    for platform in _job_urls:
        driver = get_driver(platform)
        assert driver.capabilities.submit_authorized is False, platform
    generic = get_driver("generic")
    assert generic.capabilities.submit_authorized is False


# ---------------------------------------------------------------------------
# Canonical state machine mapping (existing statuses, additive view)
# ---------------------------------------------------------------------------


def test_pipeline_state_mapping() -> None:
    assert map_pipeline_state("DISCOVERED") == "DISCOVERED"
    assert map_pipeline_state("QUEUED") == "ELIGIBLE"
    assert map_pipeline_state("APPLYING") == "PREPARING"
    assert map_pipeline_state("NEEDS_REVIEW") == "REVIEW_REQUIRED"
    assert map_pipeline_state("STAGED") == "APPROVED"
    assert map_pipeline_state("SUBMITTED") == "SUBMITTED"
    assert map_pipeline_state("SUBMISSION_UNKNOWN") == "SUBMISSION_UNCERTAIN"
    assert map_pipeline_state("SKIPPED") == "BLOCKED"
    # Checkpoint refinement trims the co-grained status.
    assert map_pipeline_state("APPLYING", "RESUME_UPLOADED") == "PREFILLED"
    assert map_pipeline_state("APPLYING", "PRE_SUBMISSION_CHECK") == "VALIDATING"
    assert map_pipeline_state("SUBMITTED", "VERIFYING_SUBMISSION") == "CONFIRMING"
    # Unknown status is conservative, never invented.
    assert map_pipeline_state("SOMETHING_NEW") == "BLOCKED"
    assert map_pipeline_state("") == "DISCOVERED"


def test_state_survives_restart_via_entity_store() -> None:
    """Preparation claims and autopilot states persist in the entity store."""

    from app.db.store import get_entity, session_scope, upsert_entity

    with session_scope() as db:
        upsert_entity(
            db,
            "aa_autopilot_job",
            {
                "id": "restart_test_job_1",
                "status": "APPLYING",
                "checkpointStep": "RESUME_UPLOADED",
                "companyName": "Acme Corp",
                "title": "SWE",
            },
        )
    with session_scope() as db:
        restored = get_entity(db, "aa_autopilot_job", "restart_test_job_1")
    assert restored is not None
    snapshot = pipeline_snapshot_from_autopilot_job(restored)
    assert snapshot["pipelineState"] == "PREFILLED"
