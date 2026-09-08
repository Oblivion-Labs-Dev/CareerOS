"""Remove replaced text, rather than only painting over it in tailored PDFs."""


def fit_bullet_paragraph(text, style, max_height):
    """Fit the template slot without clipping, overlapping, or dropping words."""
    from reportlab.platypus import Paragraph

    for size in (8.04, 7.8, 7.6, 7.4, 7.2, 7.0):
        fitted_style = style.clone("FittedBullet", fontSize=size, leading=size * 9.24 / 8.04)
        paragraph = Paragraph(text, fitted_style)
        _, height = paragraph.wrap(508, max_height)
        if height <= max_height:
            return paragraph, height
    raise ValueError("Resume bullet exceeds its template slot at a readable font size")


def remove_replaced_bullets(source: bytes) -> bytes:
    import pymupdf

    with pymupdf.open(stream=source, filetype="pdf") as document:
        page = document[0]
        height = page.rect.height
        # These are the two existing template slots used by the renderer.
        # Convert PDF bottom-left coordinates to PyMuPDF top-left coordinates.
        for x, y, width, box_height in [(48, 550, 532, 134), (48, 314, 532, 218)]:
            page.add_redact_annot(pymupdf.Rect(x, height - y - box_height, x + width, height - y), fill=(1, 1, 1))
        page.apply_redactions(images=0, graphics=0)
        return document.tobytes(garbage=4, deflate=True)
