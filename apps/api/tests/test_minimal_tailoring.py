from copy import deepcopy
from dataclasses import replace
import pymupdf
import pytest

from app.services.resume_intelligence import baseline_document as bd, minimal_tailoring as mt, semantic

JD = "Required: Kubernetes infrastructure and production recovery. Build reliable Kubernetes deployments and production automation."

@pytest.fixture
def baseline(tmp_path, monkeypatch):
    path = tmp_path / "approved.pdf"
    doc = pymupdf.open(); page = doc.new_page(width=612, height=792)
    page.insert_text((240, 30), "Approved Candidate", fontname="hebo", fontsize=14)
    page.insert_text((36, 60), "EXPERIENCE", fontname="hebo", fontsize=9)
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


def config(**kwargs):
    return mt.TailoringConfig(use_semantic=False, reorder_threshold=1, **kwargs)


def evidence(text="Built Kubernetes infrastructure and production recovery automation, reducing deployment failures 80%."):
    return [{"id":"new", "company":"Example", "role":"Engineer", "project":"Recovery", "evidenceTier":"professional", "resumeApproved":True, "currentBullet":text}]


def test_strong_resume_incumbents_not_searched_or_replaced(baseline, monkeypatch):
    # All bullets match this description, so corpus enumeration is forbidden.
    monkeypatch.setattr(mt,"_candidates",lambda _:pytest.fail("No weak slots: do not search corpus"))
    result=mt.tailor(evidence(), JD+" Required: routine weekly reports and team administration.",baseline=baseline,config=config(weak_relevance=.1))
    assert result["retentionFraction"]==1
    assert all(x["decision"]=="KEEP" for x in result["resumeBullets"])
    assert bd.render_baseline(result)==bd.approved_path().read_bytes()


def test_only_materially_better_evidence_replaces_weak_slot(baseline):
    result=mt.tailor(evidence(),JD,baseline=baseline,config=config())
    assert [b["decision"] for b in result["resumeBullets"]]==["REPLACE","KEEP","KEEP","KEEP"]
    first=result["resumeBullets"][0]
    assert first["debug"]["improvementFraction"]>.15
    assert first["optimizedBullet"]==evidence()[0]["currentBullet"]
    assert mt.validate(result,evidence())==[]
    weak=mt.tailor(evidence("Helped with routine weekly team reports and administration."),JD,baseline=baseline,config=config())
    assert all(b["decision"]=="KEEP" for b in weak["resumeBullets"])


def test_rich_runs_preserved_for_keep_and_reorder(baseline):
    result=mt.tailor([],JD,baseline=baseline,config=mt.TailoringConfig(use_semantic=False))
    assert any(b["decision"]=="REORDER" for b in result["resumeBullets"])
    for item in result["resumeBullets"]:
        original=next(b for b in baseline["bullets"] if b["id"]==item["baselineBulletId"])
        assert item["richText"]==original["richText"]
    data=bd.render_baseline(result)
    with pymupdf.open(stream=data,filetype="pdf") as doc:
        assert len(doc)==1
        text=doc[0].get_text()
        assert text.count("Original university and degree")==1
        assert text.count("Helped with reports")==1
        assert text.count("Built Kubernetes production automation")==1


def test_replacement_bold_opening_and_normal_remainder_pdf(baseline):
    result=mt.tailor(evidence(),JD,baseline=baseline,config=config())
    runs=result["resumeBullets"][0]["richText"]
    assert runs[0]["bold"] and not runs[-1]["bold"]
    assert "".join(r["text"] for r in runs)==evidence()[0]["currentBullet"]
    data=bd.render_baseline(result)
    with pymupdf.open(stream=data,filetype="pdf") as doc, pymupdf.open(bd.approved_path()) as original:
        assert len(doc)==1
        spans=[s for b in doc[0].get_text("dict")["blocks"] if b["type"]==0 for l in b["lines"] for s in l["spans"]]
        assert any(s["flags"]&16 and "Built" in s["text"] for s in spans)
        assert any(not s["flags"]&16 and "failures" in s["text"] for s in spans)
        # All pixels outside the changed slot remain identical, including headings.
        clip=pymupdf.Rect(0,120,612,792)
        assert doc[0].get_pixmap(clip=clip).samples==original[0].get_pixmap(clip=clip).samples


def test_overflow_and_unapproved_wrong_role_do_not_replace(baseline):
    for field,value in [("role","Different role"),("resumeApproved",False),("currentBullet","Built Kubernetes production recovery automation "*12+".")]:
        records=evidence();records[0][field]=value
        r=mt.tailor(records,JD,baseline=baseline,config=config())
        assert r["retentionFraction"]==1


def test_revision_and_rich_text_tampering_rejected(baseline):
    records=evidence(); r=mt.tailor(records,JD,baseline=baseline,config=config())
    changed=deepcopy(records);changed[0]["currentBullet"]+=" Changed."
    assert mt.validate(r,changed)
    r["resumeBullets"][1]["richText"][0]["bold"]=False
    assert mt.validate(r,records)
    with pytest.raises(ValueError,match="rich text"):
        bd.render_baseline(r)


def test_threshold_and_existing_rank_config_are_configurable(baseline):
    cfg=config(replacement_threshold=1,bm25_k1=1.8,bm25_b=.6,rrf_k=40,mmr_lambda=.8)
    r=mt.tailor(evidence(),JD,baseline=baseline,config=cfg)
    assert r["tailoringConfig"]["replacement_threshold"]==1
    assert r["rankingDebug"]["bm25K1"]==1.8
    assert r["rankingDebug"]["semanticAvailable"] is False
