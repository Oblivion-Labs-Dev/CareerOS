from app.services.application_assistant.application_journey import assess_receipt, evidence_path, get_application_journey, DEFAULT_CONFIRMATION
from app.db.store import session_scope, set_kv
from app.services.application_assistant.persistence import save_autopilot_job


def test_submitted_without_evidence_is_uncertain():
    assert assess_receipt({"id": "a", "status": "SUBMITTED"}, None)["state"] == "uncertain"


def test_legacy_default_confirmation_is_not_proof():
    receipt = {"jobId": "a", "confirmationText": DEFAULT_CONFIRMATION, "qwenReview": {"submissionConfirmed": True}}
    assert assess_receipt({"id": "a", "status": "SUBMITTED"}, receipt)["state"] == "uncertain"
    receipt.update(confirmationText="Thank you for applying to Acme", qwenReview={"submissionConfirmed": True, "confidence": 0.99})
    assert assess_receipt({"id": "a", "status": "SUBMITTED"}, receipt)["state"] == "uncertain"


def test_specific_review_and_matching_identity_required():
    receipt = {"jobId": "a", "confirmationText": "Acme received your application", "qwenReview": {"submissionConfirmed": True, "reason": "Confirmation page visible"}}
    assert assess_receipt({"id": "a", "status": "SUBMITTED"}, receipt)["state"] == "confirmed"
    assert assess_receipt({"id": "other", "status": "SUBMITTED"}, receipt)["state"] == "uncertain"


def test_evidence_cannot_escape_screenshot_directory(tmp_path):
    secret = tmp_path / "private.png"
    secret.write_bytes(b"not an image")
    assert evidence_path(str(secret)) is None


def test_journey_is_read_only_and_does_not_guess_links():
    with session_scope() as db:
        save_autopilot_job(db, {"id": "journey-test", "status": "SUBMITTED", "company": "Same name", "submittedAt": "2026-09-01T12:00:00Z"})
        set_kv(db, "autopilot_submission_receipts", {})
    result = get_application_journey("journey-test")
    assert result["assessment"]["state"] == "uncertain"
    assert result["linkedPipeline"] is None
    assert result["linkedEmail"] is False
    assert result["events"][0]["title"] == "Marked submitted"
