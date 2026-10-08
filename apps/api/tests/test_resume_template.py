"""Visual regression for the golden resume template.

Content may change; page geometry, margins, fonts, headings, indentation, spacing, separators and header/footer
placement may not. Structural checks always run; Word geometry checks run where Word (or LibreOffice) is installed.
"""
import hashlib
import json

import pytest

from app.services.career_compiler.docx_render import (
    WordMeasurer, formatting_drift, geometry_of, golden_document, read_trace, render_docx,
)
from app.services.career_compiler.docx_template import golden_path, inspect, load_golden, load_spec, read_parts
from app.services.career_compiler.models import Bullet
from app.services.career_compiler.store import load_store
from app.services.career_compiler.word import ConverterUnavailable, get_converter

#: Measured once from Resume.docx. A change here means the template changed, not the content.
GOLDEN_GEOMETRY = {"page": (12240, 15840), "margins_twips": 720, "header_footer_distance": 0, "body_font": ("Helvetica", 8.0),
                   "heading": ("Helvetica", 9.0, "single"), "name": ("Helvetica", 14.0), "bullet_indent": (720, 360)}
WORD_KEYS = ("page_width_pt", "page_height_pt", "header_rows", "footer_rows", "header_bottom", "footer_top",
             "body_top", "body_left_x", "bullet_glyph_x", "right_x", "dates_x")
PITCH_TOLERANCE = .15


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def golden():
    return load_golden()


def tailored(spec, golden):
    """A content-changed resume: fewer bullets, rewritten text, no summary, earlier roles dropped."""
    document = golden_document(spec, golden)
    sections = []
    for section in document.sections:
        keep = {"employment.microsoft": 3, "employment.amazon": 4}.get(section.employment_id, 0)
        bullets = [b.model_copy(update={"text": "Rewrote " + b.text[0].lower() + b.text[1:60] + ", with different content."})
                   for b in section.bullets[:keep]]
        sections.append(section.model_copy(update={"bullets": bullets}))
    skills = {g: items[:3] for g, items in document.skills.items()}
    return document.model_copy(update={"summary": None, "sections": sections, "featured": document.featured[:1], "skills": skills})


def test_golden_template_is_the_committed_artifact(spec, golden):
    assert hashlib.sha256(golden).hexdigest() == spec["golden"]["sha256"]
    assert golden_path().name == "akshay-one-page.docx"


def test_template_spec_matches_the_golden_docx(spec, golden):
    store = load_store()
    fresh = inspect(golden, store.employment, store.data.get("education") or [])
    assert json.loads(json.dumps(fresh)) == {k: v for k, v in spec.items() if k != "rendered"}, \
        "templates/akshay-one-page.template.json is stale. Run: python -m app.services.career_compiler.docx_template"
    assert spec["checks"] == [], "template text disagrees with career.json"


def test_template_geometry_fonts_and_slots_have_not_drifted(spec):
    assert (spec["page"]["width_twips"], spec["page"]["height_twips"]) == GOLDEN_GEOMETRY["page"]
    assert {spec["margins"][k]["twips"] for k in ("top", "right", "bottom", "left")} == {GOLDEN_GEOMETRY["margins_twips"]}
    assert spec["margins"]["header"]["twips"] == spec["margins"]["footer"]["twips"] == GOLDEN_GEOMETRY["header_footer_distance"]
    assert {(b["indent_left_twips"], b["hanging_twips"]) for b in spec["bullets"].values()} == {GOLDEN_GEOMETRY["bullet_indent"]}
    assert spec["headings"]["runs"][0]["font"] == GOLDEN_GEOMETRY["heading"][0]
    assert (spec["headings"]["runs"][0]["size_pt"], spec["headings"]["runs"][0]["underline"]) == GOLDEN_GEOMETRY["heading"][1:]
    assert "Helvetica 8pt" in spec["fonts_used"] and "Helvetica 8pt bold" in spec["fonts_used"] and "Helvetica 14pt bold" in spec["fonts_used"]
    assert spec["section_order"] == ["summary", "experience", "education", "projects", "skills"]
    assert [r["slot"] for r in spec["role_headers"]] == ["microsoft", "amazon"] + ["earlier_experience"] * 3
    assert len(spec["slots"]["separators"]) == 4 and len(spec["slots"]["education"]) == 2


def test_rendering_changes_text_only(spec, golden):
    for document in (golden_document(spec, golden), tailored(spec, golden)):
        docx = render_docx(document, spec, golden).docx
        assert formatting_drift(docx, golden) == []
        parts, gold = read_parts(docx), read_parts(golden)
        assert set(gold) <= set(parts)


def test_rendering_is_deterministic_and_carries_bullet_trace(spec, golden):
    document = tailored(spec, golden)
    traced = document.model_copy(update={"sections": [s.model_copy(update={"bullets": [
        b.model_copy(update={"evidence_ids": [f"{b.id}.e1"], "requirements": [{"id": "R1", "strength": "strong"}]})
        for b in s.bullets]}) for s in document.sections]})
    first, second = render_docx(traced, spec, golden).docx, render_docx(traced, spec, golden).docx
    assert first == second
    embedded = read_trace(first)
    assert {b.id for b in traced.bullets() if b.employment_id != "personal"} <= set(embedded)
    assert all(embedded[b.id] == {"project": b.project_id, "requirements": ["R1"], "evidence": [f"{b.id}.e1"], "text": b.text}
               for s in traced.sections for b in s.bullets)


def test_drift_detector_catches_formatting_changes(spec, golden):
    docx = render_docx(tailored(spec, golden), spec, golden).docx
    parts = read_parts(docx)
    from app.services.career_compiler.docx_render import _package
    bigger = parts["word/document.xml"].replace(b'w:val="16"', b'w:val="17"', 1)
    margins = parts["word/document.xml"].replace(b'w:top="720"', b'w:top="500"')
    styles = parts["word/styles.xml"].replace(b"Helvetica", b"Arial", 1) if b"Helvetica" in parts["word/styles.xml"] else parts["word/styles.xml"] + b" "
    for name, data in (("word/document.xml", bigger), ("word/document.xml", margins), ("word/styles.xml", styles)):
        assert formatting_drift(_package({**parts, name: data}), golden), f"{name} change was not detected"


def _converter():
    try:
        return get_converter()
    except ConverterUnavailable:
        pytest.skip("No Word or LibreOffice to render the template")


@pytest.mark.parametrize("variant", ["golden", "tailored"])
def test_word_geometry_matches_the_golden(spec, golden, variant):
    converter = _converter()
    document = golden_document(spec, golden) if variant == "golden" else tailored(spec, golden)
    rendered = render_docx(document, spec, golden)
    measured = WordMeasurer(spec, converter).measure(rendered)
    geometry = geometry_of(measured.pdf, spec)
    reference = spec["rendered"]
    assert measured.pages == 1 and measured.unmatched == []
    for key in WORD_KEYS:
        if key in ("dates_x",):
            assert set(geometry[key]) <= set(reference[key])
        elif key in ("footer_rows", "header_rows"):
            assert [(r["y0"], r["y1"], r["font"], r["size"]) for r in geometry[key]] == \
                   [(r["y0"], r["y1"], r["font"], r["size"]) for r in reference[key]]
        else:
            assert geometry[key] == reference[key], key
    assert set(geometry["text_columns_x"]) <= set(reference["text_columns_x"])
    assert set(geometry["fonts"]) <= set(reference["fonts"])
    for key in ("line_pitch", "bullet_pitch"):
        if geometry[key] is not None:
            assert abs(geometry[key] - reference[key]) <= PITCH_TOLERANCE, key
    if variant == "golden":
        golden_lines = reference["paragraph_lines"]
        assert {k: v for k, v in measured.lines.items() if k in golden_lines} == \
               {k: v for k, v in golden_lines.items() if k in measured.lines}
        assert measured.total_lines == reference["golden_lines"]


def test_generate_with_word_is_one_page_and_template_exact(spec, golden, tmp_path, monkeypatch):
    _converter()
    from tests.test_career_compiler import AWS_JD, fake_llm, honest_writer
    from app.services.career_compiler.deepseek import DeepSeekClient
    from app.services.career_compiler.models import ResumePlan
    from app.services.career_compiler.pipeline import analyze, generate
    monkeypatch.setenv("CAREEROS_JD_CACHE", str(tmp_path))
    monkeypatch.setenv("CAREEROS_COMPILER_DATA", str(tmp_path / "compiler"))
    result = analyze(text=AWS_JD, llm=DeepSeekClient(api_key=""))
    first = generate(jd_id=result["jd"]["id"], plan=ResumePlan.model_validate(result["plan"]), llm=fake_llm(honest_writer))
    second = generate(jd_id=result["jd"]["id"], plan=ResumePlan.model_validate(result["plan"]), llm=fake_llm(honest_writer))
    for output in (first, second):
        assert output["layout"]["engine"] != "estimate" and output["layout"]["pages"] == 1
        assert output["valid"] and output["layout"]["template_drift"] == [] and output["preview"].startswith("data:image/png")
    assert first["document"] == second["document"]


def test_word_opens_rendered_docx_and_measures_overflow(spec, golden):
    converter = _converter()
    document = golden_document(spec, golden)
    amazon = next(s for s in document.sections if s.employment_id == "employment.amazon")
    extra = [Bullet(id=f"extra{i}", employment_id=amazon.employment_id, project_id=f"extra{i}",
                    text="Added another line of content to push the resume past one page in Word.") for i in range(3)]
    document.sections[[s.employment_id for s in document.sections].index(amazon.employment_id)] = \
        amazon.model_copy(update={"bullets": amazon.bullets + extra})
    measured = WordMeasurer(spec, converter).measure(render_docx(document, spec, golden))
    assert measured.pages == 2 and measured.overflow_lines >= 3 and not measured.fits
