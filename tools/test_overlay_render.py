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

# 1. Whiteout MS
can.setFillColor(colors.white)
can.rect(48, 550, 532, 134, fill=1, stroke=0)

# 2. Whiteout AMZ
can.rect(48, 314, 532, 218, fill=1, stroke=0)

bullet_style = ParagraphStyle(
    "TestBullet",
    fontName="Helvetica",
    fontSize=7.8,
    leading=9.2,
    textColor=colors.HexColor("#000000"),
)

# Draw test bullet in MS
p1 = Paragraph("<b>Built the historical risk foundation for AI Agent Risk Detection</b>, reconstructing 90 days of activity across 40+ environments.", bullet_style)
w, h = p1.wrap(504, 50)
can.drawString(54.0, 684.0 - 7.5, chr(8226))
p1.drawOn(can, 72.0, 684.0 - h)

# Draw test bullet in AMZ
p2 = Paragraph("<b>Built a 0→1 developer platform for 60+ microservices</b>, creating a one-click CDK-based workflow that standardized infrastructure.", bullet_style)
w2, h2 = p2.wrap(504, 50)
can.drawString(54.0, 524.7 - 7.5, chr(8226))
p2.drawOn(can, 72.0, 524.7 - h2)

can.save()
packet.seek(0)
overlay_pdf = PdfReader(packet)
page.merge_page(overlay_pdf.pages[0])

writer = PdfWriter()
writer.add_page(page)
out_path = Path("apps/web/public/resumes/test_overlay.pdf")
with open(out_path, "wb") as f:
    writer.write(f)
print("Saved test_overlay.pdf successfully!")
