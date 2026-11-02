import pypdf

reader = pypdf.PdfReader('apps/api/data/Akshay_Borse_Resume_Original.pdf')
page = reader.pages[0]

text = page.extract_text()
# Split by lines
lines = text.split('\n')

bullets = []
curr = []

for line in lines:
    clean = line.strip()
    # In pypdf, bullet symbol extracted as • or ? or \u2022
    if clean.startswith('•') or clean.startswith('?') or (len(clean) > 1 and clean[0] == '\u2022'):
        if curr:
            bullets.append(" ".join(curr))
        curr = [clean.lstrip('•? \u2022').strip()]
    elif clean.startswith('______'):
        if curr:
            bullets.append(" ".join(curr))
            curr = []
    elif curr:
        curr.append(clean)

print(f"Extracted {len(bullets)} total bullets from resume:")
for idx, b in enumerate(bullets):
    safe = b.encode('ascii', errors='replace').decode()
    print(f"[{idx+1}] {safe}\n")
