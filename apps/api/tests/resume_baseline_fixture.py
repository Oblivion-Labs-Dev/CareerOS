import pymupdf
import pytest
from app.services.resume_intelligence import baseline_document as bd, semantic

@pytest.fixture
def baseline(tmp_path, monkeypatch):
    path = tmp_path / "approved.pdf"
    doc = pymupdf.open(); page = doc.new_page(width=612, height=792)
    page.insert_text((240, 30), "Approved Candidate", fontname="hebo", fontsize=14)
    page.insert_text((36, 60), "EXPERIENCE", fontname="hebo", fontsize=9)
    page.draw_line((36, 63), (576, 63))
    page.insert_text((36, 76), "Engineer | Example | Seattle", fontname="hebo", fontsize=8)
    texts = [("Helped with reports", ", supporting routine weekly team administration."),
             ("Built Kubernetes production automation", ", reducing recovery time 45% across reliable deployments."),
             ("Designed Kubernetes infrastructure", ", improving production recovery and deployment reliability 35%."),
             ("Owned reliable Kubernetes deployments", ", delivering production automation across 40 services.")]
    for i, (bold, normal) in enumerate(texts):
        y=94+i*24
        page.insert_text((54,y), "·", fontsize=8)
        page.insert_text((72,y), bold, fontname="hebo", fontsize=8)
        x=72+pymupdf.get_text_length(bold, fontname="hebo", fontsize=8)
        page.insert_text((x,y), normal, fontname="helv", fontsize=8)
    page.insert_text((36, 205), "EDUCATION", fontname="hebo", fontsize=9)
    page.insert_text((72, 220), "Original university and degree", fontsize=8)
    doc.save(path); doc.close()
    monkeypatch.setenv("CAREEROS_APPROVED_RESUME_PATH", str(path))
    monkeypatch.setattr(semantic,"embed_many",lambda _:None)
    return bd.load_baseline()
