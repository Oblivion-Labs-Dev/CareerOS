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
    assert len(receipt["certificateFingerprint"]) > 0

    fetched = get_submission_receipt(job_id)
    assert fetched is not None
    assert fetched["receiptId"] == receipt["receiptId"]
    assert fetched["company"] == "OpenAI"

    all_rcpts = list_all_submission_receipts()
    assert len(all_rcpts) >= 1
