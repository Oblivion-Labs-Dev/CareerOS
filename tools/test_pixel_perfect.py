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

# Whiteout MS: exactly covering the bullets (y=550 to 684)
can.setFillColor(colors.white)
can.rect(48, 550, 532, 134, fill=1, stroke=0)

# Whiteout AMZ: exactly covering the bullets (y=314 to 530)
can.rect(48, 314, 532, 216, fill=1, stroke=0)

bullet_style = ParagraphStyle(
    "ExactBullet",
    fontName="Helvetica",
    fontSize=8.0,
    leading=9.24,
    textColor=colors.HexColor("#000000"),
)

with open("tools/canonical_17_bullets.json", "r", encoding="utf-8") as f:
    bullets_data = json.load(f)

# The exact baseline Ys from the original PDF:
ms_ys = [677.02, 658.06, 639.10, 620.26, 601.30, 582.34, 563.38]
amz_ys = [524.70, 496.50, 477.70, 458.70, 439.80, 420.80, 401.80, 373.70, 354.80, 326.70]

def render_bullet_exact(can, y_base, prefix, full):
    # Bullet dot
    can.setFillColor(colors.HexColor("#000000"))
    can.setFont("Helvetica", 8.0)
    can.drawString(54.0, y_base, chr(8226))
    
    rest = full[len(prefix):].lstrip(' ,') if full.startswith(prefix) else full
    formatted_html = f"<b>{prefix}</b>, {rest}" if rest else f"<b>{prefix}</b>"
    
    p = Paragraph(formatted_html, bullet_style)
    w, h = p.wrap(504, 80)
    # With leading=9.24 and fontSize=8.0, first baseline is at (y_draw + h - 7.0)
    # Setting y_draw = y_base - h + 7.0 places the first line's baseline precisely at y_base
    y_draw = y_base - h + 7.0
    p.drawOn(can, 72.0, y_draw)

for idx, b in enumerate(bullets_data[:7]):
    render_bullet_exact(can, ms_ys[idx], b['boldPrefix'], b['fullText'])

for idx, b in enumerate(bullets_data[7:]):
    render_bullet_exact(can, amz_ys[idx], b['boldPrefix'], b['fullText'])

can.save()
packet.seek(0)
overlay_pdf = PdfReader(packet)
page.merge_page(overlay_pdf.pages[0])

writer = PdfWriter()
writer.add_page(page)
out_path = Path("apps/web/public/resumes/test_pixel_perfect.pdf")
with open(out_path, "wb") as f:
    writer.write(f)
print("Rendered test_pixel_perfect.pdf successfully!")
