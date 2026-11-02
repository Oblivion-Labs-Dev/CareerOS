import pypdf
import sys

reader = pypdf.PdfReader('apps/api/data/Akshay_Borse_Resume_Original.pdf')
page = reader.pages[0]

bullets_ms = []
bullets_amz = []

current_section = None

def visitor(text, cm, tm, fontDict, fontSize):
    global current_section
    x = tm[4]
    y = tm[5]
    t = text.strip()
    if not t:
        return
    # Check section headers
    if 'Microsoft' in t:
        current_section = 'ms'
        print(f"HEADER MS: y={y:.1f}, text={t}")
    elif 'Amazon' in t:
        current_section = 'amz'
        print(f"HEADER AMZ: y={y:.1f}, text={t}")
    elif 'Liquiron' in t:
        current_section = 'liq'
        print(f"HEADER LIQ: y={y:.1f}, text={t}")
    elif 'Persistent' in t:
        current_section = 'per'
        print(f"HEADER PER: y={y:.1f}, text={t}")
    elif 'EDUCATION' in t:
        current_section = 'edu'
        print(f"HEADER EDU: y={y:.1f}, text={t}")
    
    # Bullet points typically start around x=54 or 72
    font_name = fontDict.get('/BaseFont', '') if fontDict else ''
    is_bold = 'Bold' in font_name or 'bold' in font_name
    
    # Print out text with y and bold info
    if current_section in ('ms', 'amz') and 300 < y < 690:
        safe_t = t.encode('ascii', errors='replace').decode()
        if len(safe_t) > 2:
            print(f"[{current_section.upper()}] y={y:.1f}, x={x:.1f}, bold={is_bold}: {safe_t[:60]}")

page.extract_text(visitor_text=visitor)
