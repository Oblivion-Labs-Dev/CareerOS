import pypdf

reader = pypdf.PdfReader('apps/api/data/Akshay_Borse_Resume_Original.pdf')
page = reader.pages[0]

items = []

def visitor(text, cm, tm, fontDict, fontSize):
    t = text.strip()
    if not t:
        return
    font_name = fontDict.get('/BaseFont', '') if fontDict else ''
    is_bold = 'Bold' in font_name or 'bold' in font_name
    items.append({
        'text': t,
        'x': round(tm[4], 1),
        'y': round(tm[5], 1),
        'fontSize': round(fontSize, 1),
        'bold': is_bold,
    })

page.extract_text(visitor_text=visitor)

# Sort items by Y desc, then X asc
items.sort(key=lambda item: (-item['y'], item['x']))

for it in items:
    if 300 <= it['y'] <= 695:
        safe_text = it['text'].encode('ascii', errors='replace').decode()
        print(f"y={it['y']:5.1f} | x={it['x']:5.1f} | bold={str(it['bold']):<5} | {safe_text}")
