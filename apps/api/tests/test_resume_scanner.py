from app.services.resume_intelligence.scanner import deterministic_scan_fields, extract_text_from_upload


def test_deterministic_scan_extracts_bullets() -> None:
    text = """
Jane Doe
jane@example.com

MICROSOFT
• Built a Python service on Kubernetes handling 1M requests/day
• Led migration to Azure for security tooling
"""
    result = deterministic_scan_fields(text)
    assert result["contact"]["email"] == "jane@example.com"
    assert len(result["accomplishmentCandidates"]) >= 1
    assert "Python" in result["accomplishmentCandidates"][0]["bullet"]


def test_extract_text_from_plain_text() -> None:
    text = extract_text_from_upload(text="Hello resume")
    assert text == "Hello resume"
