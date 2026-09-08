import asyncio

import pytest

from app.services.application_assistant.qwen_form_reviewer import verify_submission_confirmation


@pytest.mark.parametrize("url,body,form,expected", [
    ("https://ats.example/job?ref=thanks", "", False, False),
    ("https://thanks.example/job", "", False, False),
    ("https://ats.example/job/success-engineer", "", False, False),
    ("https://ats.example/job/confirmation", "", True, False),
    ("https://ats.example/job/confirmation", "", False, True),
    ("https://ats.example/job", "Thank you for applying", False, True),
    ("https://ats.example/job", "Thank you for applying", True, False),
])
def test_confirmation_requires_specific_evidence(url, body, form, expected):
    result = asyncio.run(verify_submission_confirmation(body, url, [], "Example", "Engineer", form))
    assert result["submissionConfirmed"] is expected
