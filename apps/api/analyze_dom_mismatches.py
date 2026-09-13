import sqlite3
import json
import sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect("d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/career_os.db")
cur = conn.cursor()

cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
rows = cur.fetchall()

mismatches = []
statuses = Counter()
reasons = Counter()

for jid, pl in rows:
    p = json.loads(pl)
    st = p.get('status')
    statuses[st] += 1
    fail = p.get('failureReason') or p.get('lastError') or p.get('skipReason') or ''
    if 'DOM' in fail or 'verification' in fail.lower() or 'unfilled' in fail.lower():
        mismatches.append((jid, p))

print(f"Total autopilot jobs: {len(rows)}")
print("Status breakdown:")
for st, cnt in statuses.most_common():
    print(f"  {st}: {cnt}")

print(f"\nTotal DOM/Verification Mismatches: {len(mismatches)}")

companies = Counter()
boards = Counter()
unfilled_fields = Counter()

for jid, p in mismatches:
    comp = p.get('company') or 'Unknown'
    companies[comp] += 1
    url = p.get('applicationUrl') or ''
    board = 'other'
    if 'greenhouse.io' in url: board = 'greenhouse'
    elif 'lever.co' in url: board = 'lever'
    elif 'ashbyhq.com' in url: board = 'ashby'
    boards[board] += 1
    
    fail = p.get('failureReason') or p.get('lastError') or p.get('skipReason') or ''
    # extract field names if present
    if 'Required fields remain unfilled in the browser:' in fail:
        fields_str = fail.split('Required fields remain unfilled in the browser:')[1].strip()
        for f in fields_str.split(','):
            unfilled_fields[f.strip()[:60]] += 1
    elif 'conflicts with live DOM value' in fail:
        unfilled_fields['conflict: ' + fail[:60]] += 1

print("\nBy ATS Board:")
for b, cnt in boards.most_common():
    print(f"  {b}: {cnt}")

print("\nTop Companies with DOM Mismatches:")
for c, cnt in companies.most_common(15):
    print(f"  {c}: {cnt}")

print("\nTop Unfilled / Conflicted Fields:")
for f, cnt in unfilled_fields.most_common(20):
    print(f"  [{cnt}] {f}")

print("\nSample 5 detailed records:")
for jid, p in mismatches[:5]:
    print(f"\n--- {jid} ({p.get('company')}) ---")
    print("Title:", p.get('title'))
    print("URL:", p.get('applicationUrl'))
    print("Fail:", p.get('failureReason') or p.get('lastError'))
    print("Answers:", list((p.get('answers') or {}).items())[:5])

conn.close()
