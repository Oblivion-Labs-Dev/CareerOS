import io

from pypdf import PdfReader
from reportlab.pdfgen import canvas

from app.services.application_assistant.resume_pdf_text import remove_replaced_bullets


def test_replaced_text_is_removed_from_ats_layer_and_other_sections_survive():
    stream = io.BytesIO()
    c = canvas.Canvas(stream, pagesize=(612, 792))
    c.setFont("Helvetica", 8)
    c.drawString(72, 677, "OLD MICROSOFT BULLET")
    c.drawString(72, 524, "OLD AMAZON BULLET")
    c.drawString(72, 720, "PRESERVED HEADER")
    c.drawString(72, 290, "PRESERVED EDUCATION")
    c.linkURL("https://example.com", (72, 710, 200, 730))
    c.save()
    cleaned = PdfReader(io.BytesIO(remove_replaced_bullets(stream.getvalue())))
    text = cleaned.pages[0].extract_text()
    assert "OLD MICROSOFT" not in text
    assert "OLD AMAZON" not in text
    assert "PRESERVED HEADER" in text
    assert "PRESERVED EDUCATION" in text
    assert len(cleaned.pages[0]["/Annots"]) == 1


def test_long_bullet_fits_without_overlapping_next_slot():
    import pytest
    from reportlab.lib.styles import ParagraphStyle

    from app.services.application_assistant.resume_pdf_text import fit_bullet_paragraph

    style = ParagraphStyle("bullet", fontName="Helvetica", fontSize=8.04, leading=9.24)
    paragraph, height = fit_bullet_paragraph("Preserve all words. " * 10, style, 19)
    assert height <= 19
    assert paragraph.style.fontSize >= 7
    with pytest.raises(ValueError, match="template slot"):
        fit_bullet_paragraph("Unreasonably long text " * 300, style, 19)
