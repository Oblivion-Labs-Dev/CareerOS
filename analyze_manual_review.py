import sqlite3, json, sys, collections, re, html

conn = sqlite3.connect('data/career_os.db')
rows = conn.execute("SELECT payload FROM entities WHERE entity_type='aa_autopilot_job'").fetchall()
jobs = [json.loads(r[0]) for r in rows]

rev = [j for j in jobs if j.get('status') in ('NEEDS_REVIEW', 'MANUAL_REVIEW')]
print(f'Total manual review jobs: {len(rev)}')

# Group by company
by_company = collections.Counter(j.get('company') for j in rev)
print('\nTop companies in manual review:')
for company, count in by_company.most_common(20):
    print(f'  {company}: {count}')

# Show some details for top companies
print('\n--- Details for top companies ---')
for company, count in by_company.most_common(10):
    company_jobs = [j for j in rev if j.get('company') == company]
    print(f'\n=== {company} ({count} jobs) ===')
    for j in company_jobs[:5]:
        title = j.get('title', 'Unknown')
        status = j.get('status')
        match = j.get('matchScore', 0)
        url = j.get('applicationUrl', '')
        board = 'greenhouse' if 'greenhouse' in url.lower() else 'ashby' if 'ashby' in url.lower() else 'workday' if 'workday' in url.lower() else 'other'
        print(f'  [{status}] {title} | Match: {match}% | {board}')
        pqs = j.get('pendingQuestions') or []
        if pqs:
            for q in pqs[:3]:
                qtext = (q.get('question') or q.get('label') or q.get('text') or '')[:100]
                print(f'    Q: {qtext}')

# Also look at pending questions across all manual review jobs
print('\n\n=== PENDING QUESTIONS ACROSS ALL MANUAL REVIEW JOBS ===')
q_counter = collections.Counter()
q_jobs = collections.Counter()
examples = {}
for j in rev:
    pqs = j.get('pendingQuestions') or []
    if isinstance(pqs, str):
        try:
            pqs = json.loads(pqs)
        except Exception:
            pqs = []
    if not isinstance(pqs, list):
        continue
    for q in pqs:
        if not isinstance(q, dict):
            continue
        text = (q.get('question') or q.get('label') or q.get('text') or '').strip()
        if not text:
            continue
        text_norm = re.sub(r'\s+', ' ', text.lower()).strip()
        key = text_norm[:160]
        q_jobs[key] += 1
        q_counter[key] += 1
        qt = q.get('type') or q.get('inputType') or '?'
        examples.setdefault(key, {"q": text, "type": qt, "co": j.get("company"), "opts": (q.get("options") or [])[:6]})

print(f'Total distinct questions: {len(q_counter)}')
top = q_jobs.most_common(30)
for key, n in top:
    ex = examples[key]
    opts = ex["opts"]
    print(f'\n[{n} jobs] [{ex["type"]}] Q: {ex["q"][:140]}')
    print(f'   Example company: {ex["co"]}')
    if opts:
        print(f'   options: {opts}')