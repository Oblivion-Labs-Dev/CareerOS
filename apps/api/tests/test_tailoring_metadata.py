from app.services.application_assistant.tailoring_metadata import authorization_summary, job_match_score


def test_missing_or_zero_score_is_not_inflated():
    assert job_match_score({}) == 0
    assert job_match_score({"matchScore": 0, "score": 90}) == 0
    assert job_match_score({"matchScore": 42}) == 42
    assert job_match_score({"matchScore": float("nan")}) == 0


def test_authorization_preview_preserves_sponsorship_and_unknowns():
    text = authorization_summary({"workAuth": {"authorizedToWorkInUS": True, "requiresSponsorshipNowOrFuture": True}})
    assert "requires sponsorship" in text
    assert "Citizen" not in text
    assert "not provided" in authorization_summary({})
