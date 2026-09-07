import pypdf

reader = pypdf.PdfReader('apps/api/data/Akshay_Borse_Resume_Original.pdf')
page = reader.pages[0]

# Let's extract full text lines
lines = page.extract_text().split('\n')
capturing_ms = False
capturing_amz = False

ms_bullets = []
amz_bullets = []

for l in lines:
    clean = l.strip()
    if 'Senior Software Engineer | Microsoft' in clean:
        capturing_ms = True
        capturing_amz = False
        continue
    elif 'Software Engineer 2 | Amazon' in clean:
        capturing_ms = False
        capturing_amz = True
        continue
    elif 'Liquiron' in clean:
        capturing_amz = False
        continue
    
    if capturing_ms and clean:
        ms_bullets.append(clean)
    elif capturing_amz and clean:
        amz_bullets.append(clean)

print("=== MS LINES ===")
for b in ms_bullets:
    print("-", b.encode('ascii', errors='replace').decode())

print("\n=== AMAZON LINES ===")
for b in amz_bullets:
    print("-", b.encode('ascii', errors='replace').decode())
