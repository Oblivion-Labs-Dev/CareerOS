import pypdf
import json

reader = pypdf.PdfReader('apps/api/data/Akshay_Borse_Resume_Original.pdf')
page = reader.pages[0]

text = page.extract_text()
lines = text.split('\n')

raw_bullets = []
curr = []
for line in lines:
    clean = line.strip()
    if clean.startswith('•') or clean.startswith('?') or (len(clean) > 1 and clean[0] == '\u2022'):
        if curr:
            raw_bullets.append(" ".join(curr))
        curr = [clean.lstrip('•? \u2022').strip()]
    elif clean.startswith('______'):
        if curr:
            raw_bullets.append(" ".join(curr))
            curr = []
    elif curr:
        curr.append(clean)
if curr:
    raw_bullets.append(" ".join(curr))

# The first 17 are MS (7) and Amazon (10)
ms_raw = raw_bullets[:7]
amz_raw = raw_bullets[7:17]

print(f"MS raw count: {len(ms_raw)}, AMZ raw count: {len(amz_raw)}")

# Bold prefixes from inspection:
bold_prefixes = [
    "Built the historical risk foundation for AI Agent Risk Detection",
    "Drove architecture across Purview IRM, Entra, and DLP",
    "Led the redesign of AI-agent ingestion for independent scale and fault isolation",
    "Led AI Risk Detection's sovereign-cloud architecture and rollout across GCC, GCCH and DoD",
    "Connected investigations across Microsoft's security ecosystem",
    "Designed an AI-assisted testing workflow",
    "Designed an AI-assisted debugging workflow spanning three repositories",
    "Built a 0→1 developer platform for 60+ microservices",
    "Led a monolith-to-microservices transformation at 100K+ TPS",
    "Designed and owned the service powering ML-predicted delivery ranges",
    "Replaced static delivery-risk rules with ML-driven decisioning",
    "Launched inventory decisioning systems processing 200K+ events/day",
    "Architected built a RAG-based product recommendation system for out-of-stock items",
    "Led design and cross-functional adoption of an LLM-powered localization platform",
    "Owned the annual operational improvement roadmap across 60+ services",
    "Turned synchronized delivery for large Amazon Business orders into a first-class fulfillment capability",
    "Standardized observability and container infrastructure across 60+ services",
]

master_bullets_with_bold = []
for idx, full_b in enumerate(raw_bullets[:17]):
    prefix = bold_prefixes[idx]
    # Check if full_b starts with prefix or words in prefix
    master_bullets_with_bold.append({
        "company": "Microsoft" if idx < 7 else "Amazon",
        "boldPrefix": prefix,
        "fullText": full_b,
    })

with open("tools/canonical_17_bullets.json", "w", encoding="utf-8") as f:
    json.dump(master_bullets_with_bold, f, indent=2, ensure_ascii=False)

print("Saved canonical_17_bullets.json successfully!")
