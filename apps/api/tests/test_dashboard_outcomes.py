from datetime import UTC, datetime
from app.services.tracker.outcomes import summarize_outcomes
from app.services.tracker.pipeline import pipeline_column

NOW = datetime(2026, 9, 10, tzinfo=UTC)


def test_explicit_links_dates_and_matching_receipts():
    jobs = [{"id": "a", "status": "SUBMITTED", "submittedAt": "2026-09-01", "applicationId": "app"},
            {"id": "b", "status": "SUBMITTED", "updatedAt": "2026-09-02"},
            {"id": "c", "status": "FAILED", "submittedAt": "2026-09-03"}]
    apps = [{"id": "app", "firstResponseAt": "2026-09-03", "interviewAt": "2026-09-12"}]
    result = summarize_outcomes(jobs, apps, {"a": {"jobId": "other"}}, NOW)
    assert result["totalSubmitted"] == 2
    assert result["cohortSize"] == result["datedSubmissions"] == result["linkedRecords"] == 1
    assert result["responses"] == 1
    assert result["medianResponseDays"] == 2
    assert result["interviews"] == 0
    assert result["awaitingConfirmation"] == 2
    assert len(result["events"]) == 2
    assert result["attention"][2]["count"] == 1


def test_missing_dates_are_not_inferred_from_status():
    result = summarize_outcomes([{"id": "a", "status": "SUBMITTED", "submittedAt": "2026-09-01", "applicationId": "app"}],
        [{"id": "app", "status": "interviewing", "firstResponseAt": "2026-08-01", "interviewAt": "invalid"}], {}, NOW)
    assert result["responses"] == result["interviews"] == 0
    assert result["medianResponseDays"] is None
    assert len(result["events"]) == 1


def test_unsubmitted_forms_are_not_in_pipeline():
    assert pipeline_column({"status": "autofilled"}) is None
    assert pipeline_column({"status": "applying"}) is None
