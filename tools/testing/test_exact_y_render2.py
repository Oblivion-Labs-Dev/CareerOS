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

# Whiteout MS: y from 548 to 684
can.setFillColor(colors.white)
can.rect(48, 548, 532, 136, fill=1, stroke=0)

# Whiteout AMZ: y from 310 to 532
can.rect(48, 310, 532, 222, fill=1, stroke=0)

bullet_style = ParagraphStyle(
    "TestBullet",
    fontName="Helvetica",
    fontSize=8.0,
    leading=9.2,
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
    # y_base - 1.8 leaves the top line exactly at y_base
    p.drawOn(can, 72.0, y_base - 1.8)

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
    p.drawOn(can, 72.0, y_base - 1.8)

can.save()
packet.seek(0)
overlay_pdf = PdfReader(packet)
page.merge_page(overlay_pdf.pages[0])

writer = PdfWriter()
writer.add_page(page)
out_path = Path("apps/web/public/resumes/test_perfect_align2.pdf")
with open(out_path, "wb") as f:
    writer.write(f)
print("Rendered test_perfect_align2.pdf successfully!")
