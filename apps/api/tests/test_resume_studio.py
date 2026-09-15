import base64
from io import BytesIO
import pymupdf
import pytest
from pypdf import PdfReader
from tests.resume_baseline_fixture import baseline
from app.services.resume_intelligence import resume_studio as studio, baseline_document as bd

JD = "Required: Kubernetes deployment automation and reliable production services. Own production recovery and infrastructure."


def test_pdf_preview_and_download_share_one_page(baseline):
    result=studio.generate_studio([], {}, JD)
    data=base64.b64decode(result["pdfBase64"])
    assert len(PdfReader(BytesIO(data)).pages)==result["pageCount"]==1
    with pymupdf.open(stream=data,filetype="pdf") as doc:
        assert base64.b64decode(result["previewBase64"])==doc[0].get_pixmap(matrix=pymupdf.Matrix(2,2),alpha=False).tobytes("png")
    assert result["result"]["rankingDebug"]["semanticAvailable"] is False


def test_studio_keeps_shared_ranking_configuration(baseline):
    settings={"bm25_k1":1.8,"bm25_b":.6,"rrf_k":40,"mmr_lambda":.8,"replacement_threshold":.22}
    r=studio.generate_studio([], {"resumeTailoringConfig":settings}, JD)["result"]
    for key,value in settings.items():
        assert r["tailoringConfig"][key]==value


def test_page_overflow_baseline_fails_instead_of_rebuilding(baseline):
    path=bd.approved_path()
    with pymupdf.open(path) as doc:
        doc.new_page(); data=doc.tobytes()
    path.write_bytes(data)
    with pytest.raises(ValueError,match="one unrotated page"):
        studio.generate_studio([],{},JD)


def test_description_and_missing_baseline_errors(baseline):
    with pytest.raises(ValueError,match="full job description"):
        studio.generate_studio([],{},"hello")
    bd.approved_path().unlink()
    with pytest.raises(ValueError,match="approved baseline"):
        studio.generate_studio([],{},JD)


def test_current_profile_does_not_overwrite_approved_identity(baseline):
    r=studio.generate_studio([], {"firstName":"Unapproved", "workExperience":[{"company":"Another employer"}]}, JD)
    text=PdfReader(BytesIO(base64.b64decode(r["pdfBase64"]))).pages[0].extract_text()
    assert "Approved Candidate" in text and "Unapproved" not in text
    assert "Original university and degree" in text
def test_fast_local_override_preserves_saved_config(baseline, monkeypatch):
    from app.services.resume_intelligence.resume_studio import generate_studio
    from app.services.resume_intelligence import semantic
    calls = []
    def forbidden(*_):
        calls.append(True)
        raise AssertionError('Fast local must not load a model')
    monkeypatch.setattr(semantic, 'embed_many', forbidden)
    profile = {'resumeTailoringConfig': {'use_semantic': True, 'replacement_threshold': .22}}
    result = generate_studio([], profile, 'Required: Kubernetes infrastructure and Python production services.', use_semantic=False)
    assert result['result']['tailoringConfig']['use_semantic'] is False
    assert result['result']['tailoringConfig']['replacement_threshold'] == .22
    assert profile['resumeTailoringConfig']['use_semantic'] is True
    assert calls == []
