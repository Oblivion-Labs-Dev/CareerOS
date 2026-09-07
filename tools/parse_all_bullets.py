import pypdf

reader = pypdf.PdfReader('apps/api/data/Akshay_Borse_Resume_Original.pdf')
page = reader.pages[0]

text = page.extract_text()
# Let's find exactly the lines
lines = [l.strip() for l in text.split('\n') if l.strip()]

ms_started = False
amz_started = False
liq_started = False

ms_lines = []
amz_lines = []

for l in lines:
    if 'Senior Software Engineer | Microsoft' in l:
        ms_started = True
        amz_started = False
        continue
    elif 'Software Engineer 2 | Amazon' in l:
        ms_started = False
        amz_started = True
        continue
    elif 'Liquiron' in l:
        ms_started = False
        amz_started = False
        continue
    
    if ms_started:
        ms_lines.append(l)
    elif amz_started:
        amz_lines.append(l)

def assemble_bullets(lines_list):
    bullets = []
    curr = []
    for line in lines_list:
        if line.startswith('?') or line.startswith('\u2022') or line.startswith(''):
            if curr:
                bullets.append(' '.join(curr))
            curr = [line.lstrip('?\u2022 ').strip()]
        elif line.startswith('___'):
            break
        else:
            if curr:
                curr.append(line)
    if curr:
        bullets.append(' '.join(curr))
    return bullets

ms_b = assemble_bullets(ms_lines)
amz_b = assemble_bullets(amz_lines)

print(f"MS Bullets ({len(ms_b)}):")
for i, b in enumerate(ms_b):
    print(f"{i+1}. {b.encode('ascii', errors='replace').decode()}")

print(f"\nAMZ Bullets ({len(amz_b)}):")
for i, b in enumerate(amz_b):
    print(f"{i+1}. {b.encode('ascii', errors='replace').decode()}")
