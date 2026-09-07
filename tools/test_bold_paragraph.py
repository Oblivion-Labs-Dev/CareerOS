from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
import io
from pypdf import PdfReader, PdfWriter

packet = io.BytesIO()
can = canvas.Canvas(packet)
style = ParagraphStyle(
    "TestStyle",
    fontName="Helvetica",
    fontSize=8.0,
    leading=9.3,
    textColor=colors.HexColor("#000000"),
)

text = "<b>Built the historical risk foundation</b> for AI Agent Risk Detection, reconstructing <b>90 days</b> of activity."
p = Paragraph(text, style)
w, h = p.wrap(504, 100)
print(f"Wrapped w={w}, h={h}")
p.drawOn(can, 72, 600)
can.save()
print("Success drawing bold paragraph!")
