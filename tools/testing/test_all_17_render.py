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
    fontSize=7.8,
    leading=9.2,
    textColor=colors.HexColor("#000000"),
)

with open("tools/canonical_17_bullets.json", "r", encoding="utf-8") as f:
    bullets_data = json.load(f)

# First 7 are MS
y_ms = 684.0
for b in bullets_data[:7]:
    can.setFillColor(colors.HexColor("#000000"))
    can.setFont("Helvetica", 7.8)
    can.drawString(54.0, y_ms - 7.5, chr(8226))
    
    # Format with bold prefix
    prefix = b['boldPrefix']
    full = b['fullText']
    rest = full[len(prefix):].lstrip(' ,') if full.startswith(prefix) else full
    formatted_html = f"<b>{prefix}</b>, {rest}" if rest else f"<b>{prefix}</b>"
    
    p = Paragraph(formatted_html, bullet_style)
    w, h = p.wrap(504, 80)
    p.drawOn(can, 72.0, y_ms - h)
    y_ms -= (h + 1.2)

# Next 10 are AMZ
y_amz = 532.0
for b in bullets_data[7:]:
    can.setFillColor(colors.HexColor("#000000"))
    can.setFont("Helvetica", 7.8)
    can.drawString(54.0, y_amz - 7.5, chr(8226))
    
    prefix = b['boldPrefix']
    full = b['fullText']
    rest = full[len(prefix):].lstrip(' ,') if full.startswith(prefix) else full
    formatted_html = f"<b>{prefix}</b>, {rest}" if rest else f"<b>{prefix}</b>"
    
    p = Paragraph(formatted_html, bullet_style)
    w, h = p.wrap(504, 80)
    p.drawOn(can, 72.0, y_amz - h)
    y_amz -= (h + 1.2)

can.save()
packet.seek(0)
overlay_pdf = PdfReader(packet)
page.merge_page(overlay_pdf.pages[0])

writer = PdfWriter()
writer.add_page(page)
out_path = Path("apps/web/public/resumes/test_all_17_overlay.pdf")
with open(out_path, "wb") as f:
    writer.write(f)
print(f"End y_ms={y_ms:.1f} (limit > 548), End y_amz={y_amz:.1f} (limit > 310)")
