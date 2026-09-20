"""Know what the profile cannot answer before a run starts, not during one.

872 applications currently sit in review; 484 are blocked on a field nothing
could answer. Every one of those cost a real browser run to discover. These
cover the profile-scoped check that moves the discovery to before the run.
"""

from __future__ import annotations

import pytest

from app.services.application_assistant.profile_readiness import (
    ReadinessGap,
    evaluate_profile_readiness,
)

COMPLETE = {
    "englishLevel": "Proficient",
    "citizenshipCountry": "India",
    "state": "Washington",
    "yearsExperience": 9,
    "workExperience": [{"company": "Amazon"}, {"company": "Microsoft"}],
    "education": [{"school": "Santa Clara University", "degree": "Master's Degree"}],
    "workAuth": {"requiresSponsorshipNowOrFuture": True},
}


def _blocking_keys(profile: dict) -> set[str]:
    return {gap.profile_key for gap in evaluate_profile_readiness(profile).blocking}


def test_a_complete_profile_is_ready():
    report = evaluate_profile_readiness(COMPLETE)

    assert report.ready is True
    assert report.blocking == []


@pytest.mark.parametrize(
    ("dropped", "expected_key"),
    [
        ("englishLevel", "englishLevel"),
        ("citizenshipCountry", "citizenshipCountry"),
        ("yearsExperience", "yearsExperience"),
        ("workExperience", "workExperience"),
        ("education", "education"),
        ("workAuth", "sponsorship"),
    ],
)
def test_removing_one_answer_produces_exactly_that_gap(dropped, expected_key):
    profile = {key: value for key, value in COMPLETE.items() if key != dropped}

    keys = _blocking_keys(profile)

    assert expected_key in keys
    assert len(keys) == 1, f"dropping {dropped} should block on one thing, got {keys}"


def test_an_empty_profile_blocks_on_everything():
    report = evaluate_profile_readiness({})

    assert report.ready is False
    assert len(report.blocking) == 7


def test_a_missing_profile_is_handled():
    """The gate must survive being called before the profile has loaded."""
    assert evaluate_profile_readiness(None).ready is False


# ── Specific judgements worth pinning ────────────────────────────────────────


def test_a_derivable_timezone_is_not_a_gap():
    """Auburn, WA yields Pacific Time, so the user must not be nagged for it."""
    profile = dict(COMPLETE)
    profile.pop("state")
    profile["location"] = "Auburn, WA"

    assert "timezone" not in _blocking_keys(profile)


def test_an_underivable_location_is_a_gap():
    profile = {key: value for key, value in COMPLETE.items() if key != "state"}

    assert "timezone" in _blocking_keys(profile)


def test_sponsorship_must_be_recorded_rather_than_defaulted():
    """The regression this check exists for.

    `_get_work_auth` silently defaults `requiresSponsorshipNowOrFuture` to False
    when nothing is recorded. Telling an employer no sponsorship is needed, for
    a candidate who needs it, misrepresents them — so an unset value is a gap,
    not a default.
    """
    profile = {key: value for key, value in COMPLETE.items() if key != "workAuth"}

    assert "sponsorship" in _blocking_keys(profile)


def test_a_flat_sponsorship_answer_counts():
    profile = {key: value for key, value in COMPLETE.items() if key != "workAuth"}
    profile["sponsorship"] = "Yes"

    assert "sponsorship" not in _blocking_keys(profile)


def test_race_prefers_the_specific_option_when_the_form_offers_it():
    """Both answers are correct; which one depends on the form's granularity.

    The specific value is read from a key the candidate set explicitly, never
    inferred — inferring a narrower ancestry is the failure this codebase
    already refuses.
    """
    from app.services.application_assistant.profile_answer_resolver import (
        AnswerResolution,
        _resolve_race,
    )

    profile = {"raceEthnicity": "Asian", "raceEthnicitySpecific": "South Asian"}

    granular = AnswerResolution()
    _resolve_race(granular, profile, ["East Asian", "South Asian", "Southeast Asian"])
    assert granular.answer == "South Asian"

    broad = AnswerResolution()
    _resolve_race(broad, profile, ["White", "Black", "Asian", "Hispanic"])
    assert broad.answer == "Asian"


def test_race_without_a_recorded_specific_value_does_not_guess_one():
    from app.services.application_assistant.profile_answer_resolver import (
        AnswerResolution,
        _resolve_race,
    )

    res = AnswerResolution()
    _resolve_race(res, {"raceEthnicity": "Asian"}, ["East Asian", "South Asian", "Southeast Asian"])

    # The resolver signals "no answer" with an empty string rather than None.
    # What matters is that it picked none of the narrower ancestries.
    assert not res.answer, "a broad value must not be narrowed on the candidate's behalf"
    assert res.answer not in ("East Asian", "South Asian", "Southeast Asian")


def test_years_of_experience_is_never_assumed():
    """It used to default to 8 — a checkable fact, invented, that screening
    rules gate on."""
    profile = {key: value for key, value in COMPLETE.items() if key != "yearsExperience"}

    assert "yearsExperience" in _blocking_keys(profile)


# ── Soft gaps ────────────────────────────────────────────────────────────────


def test_soft_gaps_never_block():
    report = evaluate_profile_readiness(COMPLETE)

    assert report.ready is True
    assert report.soft, "a profile with no GPA or salary should still report soft gaps"


def test_a_missing_education_date_is_soft_not_blocking():
    """Greenhouse asks for education month and year separately, so this costs
    review time — but it must not stop a whole run."""
    report = evaluate_profile_readiness(COMPLETE)

    soft_keys = {gap.profile_key for gap in report.soft}
    assert "education" in soft_keys
    assert "education" not in {gap.profile_key for gap in report.blocking}


# ── The refusal message ──────────────────────────────────────────────────────


def test_the_summary_names_what_is_missing():
    report = evaluate_profile_readiness({})

    summary = report.summary()

    assert "missing" in summary
    assert "English proficiency" in summary


def test_a_ready_profile_summarises_as_ready():
    assert "every answer" in evaluate_profile_readiness(COMPLETE).summary()


# ── The gate on AutopilotRunner.start() ──────────────────────────────────────
#
# These mock the runner's internals deliberately. Calling start() for real on
# the allow path launches an actual batch worker and writes a live run row —
# which is exactly what happened while developing this, leaving a RUNNING run
# with no worker behind it. Assert on the decision, never on the side effect.


def _start(options: dict, profile: dict) -> dict:
    import asyncio
    from unittest.mock import patch

    from app.services.application_assistant.autopilot_runner import AutopilotRunner

    runner = AutopilotRunner.get_instance()
    with patch("app.db.store.get_kv", return_value=profile), patch.object(
        runner, "_run_batch_worker"
    ), patch.object(runner, "_ensure_queue_preprocessor"):
        return asyncio.run(runner.start(options=dict(options)))


def test_a_run_is_refused_when_the_profile_cannot_answer():
    result = _start({"batchSize": 5}, {})

    assert result.get("refused") is True
    assert result.get("reason") == "profile_incomplete"
    assert result["readiness"]["blockingCount"] == 7
    assert "missing" in result["message"]


def test_a_single_job_retry_is_never_held_by_the_gate():
    """start() is not only the console's path — per-job retry, the reprocess
    sweeps and the self-healer all call it. A deliberate retry of one job is the
    user asking for exactly that job, so it must not be blocked."""
    result = _start({"priorityJobId": "apjob_x", "batchSize": 1}, {})

    assert not result.get("refused")


def test_a_ready_profile_is_not_refused():
    result = _start({"batchSize": 5}, COMPLETE)

    assert not result.get("refused")


def test_a_gap_says_where_to_fix_it():
    """A gap the user cannot act on is a nag, not a checklist item."""
    gap = evaluate_profile_readiness({}).blocking[0].to_dict()

    assert gap["fixAt"]
    assert gap["profileKey"]
    # Same shape the per-application pending questions use, so one component
    # can render both.
    assert set(gap) >= {"question", "rawLabel", "category", "fieldType", "options"}
