import sqlite3, json, sys, collections, re, html
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
conn = sqlite3.connect("data/career_os.db")
rows = conn.execute("SELECT payload FROM entities WHERE entity_type='aa_autopilot_job'").fetchall()
jobs = [json.loads(r[0]) for r in rows]

def board_of(url):
    u = (url or "").lower()
    if "boards.greenhouse.io" in u or "greenhouse" in u:
        return "greenhouse"
    if "ashbyhq.com" in u or "ashby" in u:
        return "ashby"
    if "workday" in u or "myworkdayjobs" in u:
        return "workday"
    if "smartrecruiters" in u:
        return "smartrecruiters"
    if "myworkhours" in u or "workable" in u:
        return "workable"
    if "app.trinext" in u or "trinnet" in u:
        return "trinnet"
    if "jobvite" in u:
        return "jobvite"
    if "recruitee" in u:
        return "recruitee"
    if "lever" in u:
        return "lever"
    if "teamtailor" in u:
        return "teamtailor"
    if "paylocity" in u:
        return "paylocity"
    if "eightfold" in u:
        return "eightfold"
    if "successfactors" in u or "sap" in u:
        return "successfactors"
    if "icims" in u:
        return "icims"
    if "taleo" in u:
        return "taleo"
    if "applytojob" in u or "applyto" in u:
        return "applytojob"
    if "breezy" in u:
        return "breezy"
    return "other"

rev = [j for j in jobs if j.get("status") in ("NEEDS_REVIEW", "MANUAL_REVIEW")]
by_board = collections.Counter(board_of(j.get("applicationUrl")) for j in rev)
print("review jobs by board:", dict(by_board.most_common()))
print()

# For greenhouse+ashby: aggregate pendingQuestions text
q_counter = collections.Counter()
q_jobs = collections.Counter()
examples = {}
for j in rev:
    b = board_of(j.get("applicationUrl"))
    if b not in ("greenhouse", "ashby"):
        continue
    pqs = j.get("pendingQuestions") or []
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
        text = (q.get("question") or q.get("label") or q.get("text") or "").strip()
        if not text:
            continue
        text_norm = re.sub(r"\s+", " ", text.lower()).strip()
        # strip trailing punctuation variance
        key = text_norm[:160]
        q_jobs[key] += 1
        q_counter[key] += 1
        qt = q.get("type") or q.get("inputType") or "?"
        examples.setdefault(key, {"q": text, "type": qt, "board": b, "co": j.get("company"), "opts": (q.get("options") or [])[:6]})

print(f"greenhouse/ashby review jobs with >=1 pending question:")
top = q_jobs.most_common(30)
for key, n in top:
    ex = examples[key]
    opts = ex["opts"]
    print(f"\n[{n} jobs] [{ex['board']}] [{ex['type']}] Q: {ex['q'][:140]}")
    if opts:
        print(f"   options: {opts}")
