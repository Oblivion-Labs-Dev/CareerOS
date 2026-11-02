import pypdf
import json

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
        curr = []
    elif curr is not None and 315 < it['y'] < 685:
        if it['text'].startswith('____') or 'Software Engineer' in it['text']:
            bullets.append(curr)
            curr = None
        else:
            curr.append(it)
if curr:
    bullets.append(curr)

def clean_bullet_html(b_parts):
    res = []
    for p in b_parts:
        t = p['text']
        if p['bold']:
            res.append(f"<b>{t}</b>")
        else:
            res.append(t)
    merged = " ".join(res)
    while "</b> <b>" in merged:
        merged = merged.replace("</b> <b>", " ")
    while "</b><b>" in merged:
        merged = merged.replace("</b><b>", "")
    return merged

html_bullets = [clean_bullet_html(b) for b in bullets]

with open('tools/canonical_bullets.json', 'w', encoding='utf-8') as f:
    json.dump(html_bullets, f, indent=2, ensure_ascii=False)
print(f"Exported {len(html_bullets)} bullets to tools/canonical_bullets.json successfully!")
