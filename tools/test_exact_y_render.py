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

# Whiteout MS
can.setFillColor(colors.white)
can.rect(48, 550, 532, 134, fill=1, stroke=0)

# Whiteout AMZ
can.rect(48, 314, 532, 218, fill=1, stroke=0)

bullet_style = ParagraphStyle(
    "TestBullet",
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

for idx, b in enumerate(bullets_data[:7]):
    y_base = ms_ys[idx]
    can.setFillColor(colors.HexColor("#000000"))
    can.setFont("Helvetica", 8.0)
    can.drawString(54.0, y_base, chr(8226))
    
    prefix = b['boldPrefix']
    full = b['fullText']
    rest = full[len(prefix):].lstrip(' ,') if full.startswith(prefix) else full
    formatted_html = f"<b>{prefix}</b>, {rest}" if rest else f"<b>{prefix}</b>"
    
    p = Paragraph(formatted_html, bullet_style)
    w, h = p.wrap(504, 80)
    # The first line of Paragraph has baseline at ~ (y_top - fontSize)
    # So if we place paragraph top at y_base + 6.8 pt, the first line's baseline lands exactly at y_base!
    p.drawOn(can, 72.0, y_base + 6.8 - h)

for idx, b in enumerate(bullets_data[7:]):
    y_base = amz_ys[idx]
    can.setFillColor(colors.HexColor("#000000"))
    can.setFont("Helvetica", 8.0)
    can.drawString(54.0, y_base, chr(8226))
    
    prefix = b['boldPrefix']
    full = b['fullText']
    rest = full[len(prefix):].lstrip(' ,') if full.startswith(prefix) else full
    formatted_html = f"<b>{prefix}</b>, {rest}" if rest else f"<b>{prefix}</b>"
    
    p = Paragraph(formatted_html, bullet_style)
    w, h = p.wrap(504, 80)
    p.drawOn(can, 72.0, y_base + 6.8 - h)

can.save()
packet.seek(0)
overlay_pdf = PdfReader(packet)
page.merge_page(overlay_pdf.pages[0])

writer = PdfWriter()
writer.add_page(page)
out_path = Path("apps/web/public/resumes/test_perfect_align.pdf")
with open(out_path, "wb") as f:
    writer.write(f)
print("Rendered test_perfect_align.pdf successfully!")
