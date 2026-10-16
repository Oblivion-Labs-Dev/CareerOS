import base64

import pytest
from fastapi.testclient import TestClient

from app.db.store import session_scope, set_kv
from app.main import app
from app.services.resume_parser import extract_text_from_attachment, parse_resume_into_profile

client = TestClient(app)


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


# ── /api/parse-resume: the route itself, not just the service function ──────
#
# Two handlers were once registered for this exact path. FastAPI matches
# routes in registration order, so the first — calling
# `parse_resume_into_profile(text)` with one positional argument against a
# function that takes `(profile, documents, *, force=False)` — silently
# shadowed the second, correct one on every request, and crashed with a
# TypeError the moment it ran. Nothing caught this because the only existing
# tests called the service function directly, never the route, so the
# duplicate-registration bug had no coverage. This talks to the route through
# TestClient specifically so a regression here fails loudly again.


def test_parse_resume_route_fills_the_profile_from_the_uploaded_text() -> None:
    resume_text = "Jordan Rivera\njordan.rivera@example.com\n(555) 123-4567\n8 years of experience\n"
    with session_scope() as db:
        set_kv(db, "documents", {
            "defaultResume": {
                "base64": base64.b64encode(resume_text.encode()).decode("ascii"),
                "name": "resume.txt",
            }
        })
        set_kv(db, "profile", {})

    response = client.post("/api/parse-resume", json={"force": True})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["profile"]["email"] == "jordan.rivera@example.com"
    assert body["profile"]["fullName"] == "Jordan Rivera"


def test_parse_resume_route_reports_an_unreadable_document_as_400_not_500() -> None:
    """The broken handler would have 500'd with a bare TypeError instead of
    reaching this ValueError-to-400 translation at all."""
    with session_scope() as db:
        set_kv(db, "documents", {"defaultResume": {"base64": "%%%", "name": "resume.pdf"}})
        set_kv(db, "profile", {})

    response = client.post("/api/parse-resume", json={"force": True})

    assert response.status_code == 400
    assert "Could not extract text" in response.json().get("detail", "")


def test_extract_docx_text_from_package() -> None:
    import io
    import zipfile
    from app.services.resume_parser import extract_docx_text, extract_text_from_attachment

    # Create dummy docx package
    buf = io.BytesIO()
    xml_content = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:body>
            <w:p><w:r><w:t>Alex Morgan</w:t></w:r></w:p>
            <w:p><w:r><w:t>alex@example.com</w:t></w:r></w:p>
        </w:body>
    </w:document>"""
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml_content)

    raw_bytes = buf.getvalue()
    text = extract_docx_text(raw_bytes)
    assert "Alex Morgan" in text
    assert "alex@example.com" in text

    # Test via extract_text_from_attachment
    attachment = {
        "base64": base64.b64encode(raw_bytes).decode("ascii"),
        "name": "resume.docx",
        "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    extracted = extract_text_from_attachment(attachment)
    assert "Alex Morgan" in extracted


def test_parse_resume_fields_with_structured_llm_data() -> None:
    from app.services.resume_parser import parse_resume_fields

    text = "Jane Doe\njane@example.com\n(555) 987-6543\n"
    llm_mock = {
        "fullName": "Jane Doe",
        "firstName": "Jane",
        "lastName": "Doe",
        "currentTitle": "Principal Engineer",
        "currentCompany": "Stripe",
        "city": "Seattle",
        "state": "Washington",
        "yearsExperience": 10,
        "workExperience": [
            {
                "company": "Stripe",
                "jobTitle": "Principal Engineer",
                "startDate": "01/2020",
                "endDate": "Present",
                "currentlyEmployed": True,
            }
        ],
        "education": [
            {
                "school": "University of Washington",
                "degree": "B.S. Computer Science",
                "endYear": "2014",
            }
        ],
        "skills": ["Distributed Systems", "Python", "Go"],
    }

    updated, extracted = parse_resume_fields(text, {}, llm_data=llm_mock)
    assert updated["fullName"] == "Jane Doe"
    assert updated["email"] == "jane@example.com"
    assert updated["currentCompany"] == "Stripe"
    assert updated["city"] == "Seattle"
    assert len(updated["workExperience"]) == 1
    assert updated["workExperience"][0]["company"] == "Stripe"
    assert len(updated["education"]) == 1
    assert "Distributed Systems" in updated["skills"]

