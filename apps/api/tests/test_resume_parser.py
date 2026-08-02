import base64

import pytest

from app.services.resume_parser import extract_text_from_attachment, parse_resume_into_profile


def test_extract_text_returns_empty_for_invalid_pdf_bytes() -> None:
    attachment = {
        "base64": base64.b64encode(b"not a pdf").decode("ascii"),
        "name": "resume.pdf",
        "type": "application/pdf",
    }

    assert extract_text_from_attachment(attachment) == ""


def test_extract_text_returns_empty_for_invalid_base64() -> None:
    assert extract_text_from_attachment({"base64": "%%%", "name": "resume.txt"}) == ""


def test_explicit_resume_parse_reports_unreadable_document() -> None:
    documents = {"defaultResume": {"base64": "%%%", "name": "resume.pdf"}}

    with pytest.raises(ValueError, match="Could not extract text"):
        parse_resume_into_profile({}, documents)
