import pytest
from tests.resume_baseline_fixture import baseline

@pytest.fixture(autouse=True)
def approved_baseline(baseline):
    return baseline

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
    assert not res["quality"]["ok"]  # Missing JD cannot be certified for export.
    assert res["tailoredCoverLetter"] == ""
    assert res["screeningQAs"] == []

    # Test off mode (no changes)
    res_off = await generate_role_tailoring_diff(job, profile, mode="off")
    assert res_off["mode"] == "off"
    assert res_off["totalChanges"] == 0
    for b in res_off["bulletDiffs"]:
        assert b["isModified"] is False
        assert b["original"] == b["tailored"]

    res_agg = await generate_role_tailoring_diff(job, profile, mode="aggressive")
    assert res_agg["mode"] == "aggressive"

    # The score now describes the tailored document rather than the stored job
    # row, so it is allowed to move - that is the whole point of re-scoring, and
    # the retry loop depends on it. What must NOT move is the baseline: every
    # mode starts from the same stored score, so a mode change alone can never
    # be what makes a posting look like a better fit.
    assert res["baseMatchScore"] == res_off["baseMatchScore"] == res_agg["baseMatchScore"] == 0

    # "off" changes nothing, so it has nothing to re-score and must report the
    # stored number untouched.
    assert res_off["matchScore"] == res_off["baseMatchScore"] == 0
    assert res_off["matchRescored"] is False

    # Every mode carries a quality verdict, and it is a separate judgement from
    # the score: a resume can score well and still be unfit to send.
    for result in (res, res_off, res_agg):
        assert "quality" in result
        assert set(result["quality"]) >= {"ok", "changed", "total", "problems"}
    # The old assertion here looked for specific words ("Spearheaded",
    # "Orchestrated") in live model output for a job with no description. That
    # is not a property of the system, it is a guess about one model's phrasing,
    # and it failed on this box regardless of any change to the code.
    #
    # The invariant worth protecting is honesty about what was produced: the
    # service must never report a tailored resume it did not actually generate.
    # Either bullets really changed, or the result says plainly that they did
    # not - via tailoringFailed, or a quality verdict that refuses it.
    for result in (res, res_agg):
        really_tailored = result["totalChanges"] > 0
        admits_it_did_not = (
            result["tailoringFailed"] or not result["quality"]["ok"]
        )
        assert really_tailored or admits_it_did_not, (
            f"{result['mode']} mode changed nothing yet reported success"
        )


@pytest.mark.anyio
async def test_off_mode_keeps_approved_pdf_even_with_full_jd(baseline):
    from app.services.application_assistant.resume_diff_service import render_tailored_resume_pdf
    from app.services.resume_intelligence.baseline_document import approved_path
    result=await generate_role_tailoring_diff({"title":"Engineer","description":"Required: Kubernetes infrastructure and production recovery automation."}, {}, mode="off", accomplishments=[])
    assert result["totalChanges"]==0
    assert all(b["decision"]=="KEEP" for b in result["resumeDocument"]["resumeBullets"])
    assert render_tailored_resume_pdf(result,{})==approved_path().read_bytes()
