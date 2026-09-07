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
        'bold': is_bold,
    })

page.extract_text(visitor_text=visitor)
items.sort(key=lambda item: (-item['y'], item['x']))

bullets = []
curr = None
for it in items:
    if it['x'] == 54.0 and 315 < it['y'] < 685:
        if curr:
            bullets.append(curr)
        curr = [it]
    elif curr is not None and 315 < it['y'] < 685:
        if it['text'].startswith('____') or 'Software Engineer' in it['text']:
            bullets.append(curr)
            curr = None
        else:
            curr.append(it)
if curr:
    bullets.append(curr)

for idx, b in enumerate(bullets):
    bold_parts = [p['text'] for p in b if p['bold']]
    bold_str = " ".join(bold_parts).encode('ascii', errors='replace').decode()
    print(f"B{idx+1}: BOLD = [{bold_str}]")
