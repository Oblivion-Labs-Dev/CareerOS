import pytest
from app.services.application_assistant.resume_diff_service import (
    compute_text_diff_chunks,
    compute_bullet_diffs,
    generate_role_tailoring_diff,
)

def test_compute_text_diff_chunks():
    orig = "Architected distributed backend systems with Python."
    mod = "Architected scalable distributed backend systems with Python and Go."
    chunks = compute_text_diff_chunks(orig, mod)
    
    assert len(chunks) > 0
    additions = [c["text"] for c in chunks if c["type"] == "add"]
    assert any("scalable" in a for a in additions) or any("and Go." in a for a in additions)

def test_compute_bullet_diffs():
    master = ["Built microservices in Go.", "Managed SQL databases."]
    tailored = ["Built high-throughput microservices in Go.", "Managed SQL databases."]
    diffs = compute_bullet_diffs(master, tailored)
    
    assert len(diffs) == 2
    assert diffs[0]["isModified"] is True
    assert diffs[1]["isModified"] is False

@pytest.mark.anyio
async def test_generate_role_tailoring_diff():
    job = {"id": "test_job_1", "company": "Vercel", "title": "Staff AI Engineer"}
    profile = {
        "firstName": "Akshay",
        "lastName": "Borse",
        "experience": [{"highlights": ["Designed AI pipelines in PyTorch."]}],
    }
    
    # Test honest mode
    res = await generate_role_tailoring_diff(job, profile, mode="honest")
    assert res["company"] == "Vercel"
    assert res["title"] == "Staff AI Engineer"
    assert res["mode"] == "honest"
    assert len(res["bulletDiffs"]) > 0
    assert "Vercel" in res["tailoredCoverLetter"]
    assert len(res["screeningQAs"]) >= 2

    # Test off mode (no changes)
    res_off = await generate_role_tailoring_diff(job, profile, mode="off")
    assert res_off["mode"] == "off"
    assert res_off["totalChanges"] == 0
    for b in res_off["bulletDiffs"]:
        assert b["isModified"] is False
        assert b["original"] == b["tailored"]

    # Tailoring mode cannot manufacture a higher match score.
    res_agg = await generate_role_tailoring_diff(job, profile, mode="aggressive")
    assert res_agg["mode"] == "aggressive"
    assert res_agg["matchScore"] == res["matchScore"] == res_off["matchScore"] == 0
    assert any("multi-agent" in b["tailored"] or "Spearheaded" in b["tailored"] or "Orchestrated" in b["tailored"] for b in res_agg["bulletDiffs"])
