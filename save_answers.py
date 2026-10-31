import sqlite3
import json
from datetime import datetime, timezone

conn = sqlite3.connect('data/career_os.db')
conn.row_factory = sqlite3.Row

# Check the entities table schema
cursor = conn.execute("PRAGMA table_info(entities)")
print("Entities columns:", [row[1] for row in cursor.fetchall()])

# Check for autopilot jobs
cursor = conn.execute('SELECT COUNT(*) FROM entities WHERE entity_type="aa_autopilot_job"')
print(f"Autopilot jobs: {cursor.fetchone()[0]}")

# Check for answer library
cursor = conn.execute('SELECT COUNT(*) FROM entities WHERE entity_type="aa_answer_library"')
print(f"Answer library entries: {cursor.fetchone()[0]}")

# Look at manual review jobs and their pending questions
cursor = conn.execute('SELECT payload FROM entities WHERE entity_type="aa_autopilot_job" AND json_extract(payload, "$.status") IN ("NEEDS_REVIEW", "MANUAL_REVIEW") LIMIT 20')
jobs = [json.loads(row[0]) for row in cursor.fetchall()]

print(f"\nManual review jobs found: {len(jobs)}")

# Collect all pending questions
all_questions = {}
for job in jobs:
    pqs = job.get('pendingQuestions') or []
    if isinstance(pqs, str):
        try:
            pqs = json.loads(pqs)
        except:
            pqs = []
    if not isinstance(pqs, list):
        continue
    for q in pqs:
        if not isinstance(q, dict):
            continue
        text = (q.get('question') or q.get('label') or q.get('text') or '').strip()
        if not text:
            continue
        key = text.lower()[:200]
        if key not in all_questions:
            all_questions[key] = {
                'text': text,
                'type': q.get('type') or q.get('inputType') or '?',
                'options': q.get('options') or [],
                'companies': set(),
                'count': 0
            }
        all_questions[key]['companies'].add(job.get('company', 'Unknown'))
        all_questions[key]['count'] += 1

print(f"\nDistinct pending questions across manual review jobs: {len(all_questions)}")
print("\n=== TOP QUESTIONS ===")
for key, info in sorted(all_questions.items(), key=lambda x: -x[1]['count'])[:30]:
    print(f"\n[{info['count']} jobs] [{info['type']}] {info['text'][:150]}")
    print(f"   Companies: {', '.join(sorted(info['companies']))[:100]}")
    if info['options']:
        print(f"   Options: {info['options'][:6]}")

conn.close()