import sqlite3
import json
from collections import Counter

conn = sqlite3.connect("apps/api/data/career_os.db")
cur = conn.cursor()

cur.execute("SELECT payload FROM entities WHERE entity_type = 'model_usage_event'")
rows = cur.fetchall()

qwen_calls = 0
qwen_success = 0
qwen_failure = 0
tasks = Counter()
models = Counter()

for r in rows:
    p = json.loads(r[0])
    m = p.get("model", "")
    models[m] += 1
    if "qwen" in m.lower():
        qwen_calls += 1
        if p.get("success"):
            qwen_success += 1
        else:
            qwen_failure += 1
        tasks[p.get("task", "unspecified")] += 1

print("Total model_usage_events recorded:", len(rows))
print("\nBreakdown by model:")
for m, count in models.most_common(10):
    print(f"  {m}: {count}")

print(f"\nTotal Qwen invocations: {qwen_calls}")
print(f"Successfully resolved by Qwen: {qwen_success} ({qwen_success/qwen_calls*100:.1f}%)" if qwen_calls else "0")
print(f"Failed / Timed out: {qwen_failure}")
print("\nTasks handled by Qwen:")
for t, count in tasks.most_common():
    print(f"  {t}: {count}")

# Check answer_library / learned_answer entities
cur.execute("SELECT COUNT(*), payload FROM entities WHERE entity_type IN ('aa_form_field', 'learned_answer') GROUP BY entity_type")
print("\nForm fields / answers:")
for r in cur.fetchall():
    print(f"  {r[0]} entities of type")
