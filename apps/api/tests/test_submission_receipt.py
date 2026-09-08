import pytest
from app.services.application_assistant.submission_receipt_service import (
    create_submission_receipt,
    get_submission_receipt,
    list_all_submission_receipts,
)

def test_submission_receipt_archival():
    job_id = "test_job_receipt_123"
    company = "OpenAI"
    title = "Research Engineer"
    app_url = "https://jobs.ashbyhq.com/openai/test-123"
    conf_url = "https://jobs.ashbyhq.com/openai/test-123/confirmation"
    conf_text = "Thank you for applying to OpenAI!"
    fields = {"First Name": "Akshay", "Email": "amsborse@gmail.com"}

    receipt = create_submission_receipt(
        job_id=job_id,
        company=company,
        title=title,
        application_url=app_url,
        confirmation_url=conf_url,
        confirmation_text=conf_text,
        fields_filled=fields,
    )

    assert receipt["receiptId"].startswith("rcpt_")
    assert receipt["company"] == "OpenAI"
    assert receipt["verificationStatus"] == "VERIFIED"
    assert receipt["submissionStatus"] == "SUBMISSION_CONFIRMED"
    assert receipt["fieldVerificationStatus"] == "FIELD_VALUES_VERIFIED"
    assert len(receipt["certificateFingerprint"]) > 0

    fetched = get_submission_receipt(job_id)
    assert fetched is not None
    assert fetched["receiptId"] == receipt["receiptId"]
    assert fetched["company"] == "OpenAI"

    all_rcpts = list_all_submission_receipts()
    assert len(all_rcpts) >= 1


def test_submission_receipt_decoupled_status_and_resume_file():
    receipt = create_submission_receipt(
        job_id="test_job_decoupled_456",
        company="Affirm",
        title="Staff Software Engineer",
        application_url="https://jobs.lever.co/affirm/test-456",
        confirmation_url="https://jobs.lever.co/affirm/test-456/thanks",
        confirmation_text="Application received!",
        fields_filled={"Resume": "Akshay_Borse_Resume_HONEST.pdf", "Preferred Name": "Akshay"},
        field_verification_status="FIELD_VALUES_MISMATCH",
        resume_file_used=None,  # Should infer from fields_filled['Resume']
    )

    assert receipt["submissionStatus"] == "SUBMISSION_CONFIRMED"
    assert receipt["fieldVerificationStatus"] == "FIELD_VALUES_MISMATCH"
    assert receipt["resumeFileUsed"] == "Akshay_Borse_Resume_HONEST.pdf"

