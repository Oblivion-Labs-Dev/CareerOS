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

# Group items by bullet (a bullet starts when x == 54.0)
bullets = []
curr_bullet = None

for it in items:
    if it['x'] == 54.0 and it['y'] < 685 and it['y'] > 300:
        if curr_bullet:
            bullets.append(curr_bullet)
        curr_bullet = {'y': it['y'], 'parts': []}
    elif curr_bullet is not None and it['y'] < 685 and it['y'] > 300:
        if it['text'].startswith('____') or 'Software Engineer' in it['text']:
            bullets.append(curr_bullet)
            curr_bullet = None
        else:
            curr_bullet['parts'].append(it)

if curr_bullet:
    bullets.append(curr_bullet)

print(f"Found {len(bullets)} bullets total:")
for i, b in enumerate(bullets):
    # reconstruct html text with <b>
    html_spans = []
    for p in b['parts']:
        if p['bold']:
            html_spans.append(f"<b>{p['text']}</b>")
        else:
            html_spans.append(p['text'])
    text = " ".join(html_spans).replace("</b> <b>", " ")
    print(f"\n--- Bullet {i+1} (y={b['y']}) ---")
    print(text.encode('ascii', errors='replace').decode())
