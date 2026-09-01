import pytest
from app.services.application_assistant.inbound_email_tracker import (
    classify_inbound_email,
    process_inbound_email,
)

def test_classify_interview_email():
    subj = "Next Steps: Software Engineer Interview with OpenAI"
    body = "Hi Akshay, we would love to schedule an interview with you. Please select a time on Calendly."
    res = classify_inbound_email(subj, body)
    assert res["eventType"] == "INTERVIEW_INVITE"
    assert res["status"] == "INTERVIEWING"
    assert res["confidence"] >= 0.9

def test_classify_rejection_email():
    subj = "Update regarding your application"
    body = "Unfortunately, we have decided to pursue other candidates whose skills align more closely."
    res = classify_inbound_email(subj, body)
    assert res["eventType"] == "REJECTION"
    assert res["status"] == "REJECTED"

def test_process_inbound_email():
    record = process_inbound_email(
        sender="recruiting@linear.app",
        subject="Interview with Linear",
        body="Let's schedule a chat to discuss next steps in our engineering process.",
    )
    assert record["id"].startswith("email_")
    assert record["classification"]["status"] == "INTERVIEWING"
