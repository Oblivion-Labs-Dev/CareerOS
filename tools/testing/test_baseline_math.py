import json
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
import io
from pypdf import PdfReader, PdfWriter
from pathlib import Path

orig_path = Path("apps/api/data/Akshay_Borse_Resume_Original.pdf")
reader = PdfReader(str(orig_path))
page = reader.pages[0]

packet = io.BytesIO()
can = canvas.Canvas(packet, pagesize=(page.mediabox.width, page.mediabox.height))

# 1. Whiteout MS bullets
can.setFillColor(colors.white)
can.rect(48, 550, 532, 134, fill=1, stroke=0)

# 2. Whiteout AMZ bullets
can.rect(48, 314, 532, 218, fill=1, stroke=0)

bullet_style = ParagraphStyle(
    "ExactBullet",
    fontName="Helvetica",
    fontSize=8.0,
    leading=9.3,
    textColor=colors.HexColor("#000000"),
)

with open("tools/canonical_17_bullets.json", "r", encoding="utf-8") as f:
    bullets_data = json.load(f)

# The exact baseline Ys from the original PDF:
ms_ys = [677.0, 658.1, 639.1, 620.3, 601.3, 582.3, 563.4]
amz_ys = [524.7, 496.5, 477.7, 458.7, 439.8, 420.8, 401.8, 373.7, 354.8, 326.7]

def render_bullet_at(can, y_base, prefix, full):
    # Draw bullet dot
    can.setFillColor(colors.HexColor("#000000"))
    can.setFont("Helvetica", 8.0)
    can.drawString(54.0, y_base, chr(8226))
    
    rest = full[len(prefix):].lstrip(' ,') if full.startswith(prefix) else full
    formatted_html = f"<b>{prefix}</b>, {rest}" if rest else f"<b>{prefix}</b>"
    
    p = Paragraph(formatted_html, bullet_style)
    w, h = p.wrap(504, 80)
    
    # Measure lines: 1-line vs 2-line vs 3-line
    # If 1-line: h is ~9.3. If 2-line: h is ~18.6. If 3-line: h is ~27.9.
    # We want line 1 to have baseline at y_base.
    # In ReportLab, for Paragraph(fontSize=8.0, leading=9.3),
    # the baseline of line 1 is at y_draw + h - 7.5.
    # Therefore, y_draw = y_base - h + 7.5 !
    y_draw = y_base - h + 7.5
    p.drawOn(can, 72.0, y_draw)

for idx, b in enumerate(bullets_data[:7]):
    render_bullet_at(can, ms_ys[idx], b['boldPrefix'], b['fullText'])

for idx, b in enumerate(bullets_data[7:]):
    render_bullet_at(can, amz_ys[idx], b['boldPrefix'], b['fullText'])

can.save()
packet.seek(0)
overlay_pdf = PdfReader(packet)
page.merge_page(overlay_pdf.pages[0])

writer = PdfWriter()
writer.add_page(page)
out_path = Path("apps/web/public/resumes/test_baseline_math.pdf")
with open(out_path, "wb") as f:
    writer.write(f)
print("Rendered test_baseline_math.pdf successfully!")
