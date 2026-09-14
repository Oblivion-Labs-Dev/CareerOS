import base64
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.services.resume_intelligence import resume_studio as studio, semantic


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(studio, "ORIGINAL", tmp_path / "no-reference.pdf")
    monkeypatch.setattr(semantic, "embed_many", lambda items: None)


def records():
    return [{"id": "platform", "company": "Example", "evidenceTier": "professional", "project": "Deployment platform",
             "currentBullet": "Built Kubernetes deployment automation, improving reliable recovery across production services.",
             "technologies": ["Kubernetes"]}]


JD = "Required: Kubernetes deployment automation and reliable production services. Own production recovery and infrastructure."


def test_pdf_preview_and_download_share_one_page():
    result = studio.generate_studio(records(), {"firstName": "Alex", "lastName": "Morgan", "email": "alex@example.test",
             "workExperience": [{"company": "Example", "jobTitle": "Engineer", "startDate": "2022", "endDate": "Present"}]}, JD)
    pdf = PdfReader(BytesIO(base64.b64decode(result["pdfBase64"])))
    assert result["pageCount"] == len(pdf.pages) == 1
    text = pdf.pages[0].extract_text()
    assert "Alex Morgan" in text and "Built Kubernetes deployment automation" in text
    assert "EXPERIENCE" in text and "SKILLS" in text
    assert base64.b64decode(result["previewBase64"]).startswith(b"\x89PNG\r\n\x1a\n")
    assert result["result"]["rankingDebug"]["bm25K1"] == 1.5
    assert result["result"]["rankingDebug"]["semanticAvailable"] is False


def test_studio_keeps_shared_ranking_configuration(monkeypatch):
    original = studio.compose
    observed = []
    def spy(*args, **kwargs):
        observed.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(studio, "compose", spy)
    studio.generate_studio(records(), {}, JD)
    assert observed
    assert all(set(options) == {"char_budget", "max_bullets"} for options in observed)


def test_page_overflow_fails_instead_of_exporting_multiple_pages():
    profile = {"workExperience": [{"company": f"Employer {i}", "jobTitle": "Engineer"} for i in range(65)]}
    with pytest.raises(ValueError, match="exceed one page"):
        studio.generate_studio(records(), profile, JD)


def test_description_and_empty_evidence_errors_are_actionable():
    with pytest.raises(ValueError, match="full job description"):
        studio.generate_studio(records(), {}, "hello")
    with pytest.raises(ValueError, match="No source-backed"):
        studio.generate_studio([], {}, JD)


def test_current_profile_identity_is_preserved(monkeypatch):
    monkeypatch.setattr(studio, "_reference", lambda *_: {"firstName": "Old", "email": "old@example.test"})
    monkeypatch.setattr(studio, "ORIGINAL", Path(__file__))
    merged = studio.reference_profile({"firstName": "Current", "email": "current@example.test"})
    assert merged["firstName"] == "Current" and merged["email"] == "current@example.test"
