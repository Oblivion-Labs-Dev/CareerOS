from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
import json

bullet_style = ParagraphStyle(
    'BStyle',
    fontName='Helvetica',
    fontSize=7.8,
    leading=9.2,
    textColor=colors.HexColor('#000000'),
)

with open('tools/canonical_17_bullets.json', 'r', encoding='utf-8') as f:
    bullets_data = json.load(f)

# Microsoft
total_h_ms = 0
for b in bullets_data[:7]:
    text = "<b>" + b['boldPrefix'] + "</b> " + b['fullText'][len(b['boldPrefix']):]
    p = Paragraph(text, bullet_style)
    w, h = p.wrap(504, 100)
    total_h_ms += h + 1.2
print(f"MS total height: {total_h_ms:.1f} (Available space: {684 - 548:.1f})")

# Amazon
total_h_amz = 0
for b in bullets_data[7:]:
    text = "<b>" + b['boldPrefix'] + "</b> " + b['fullText'][len(b['boldPrefix']):]
    p = Paragraph(text, bullet_style)
    w, h = p.wrap(504, 100)
    total_h_amz += h + 1.2
print(f"AMZ total height: {total_h_amz:.1f} (Available space: {532 - 310:.1f})")
