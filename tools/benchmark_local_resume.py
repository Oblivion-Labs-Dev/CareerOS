"""Read-only local composer benchmark; never contacts a model or modifies profile data."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
from app.db.resume_corpus_seed import resume_corpus_seed_to_accomplishment
from app.db.story_corpus_sync import _apply, STORY_TO_ACCOMPLISHMENT
from app.services.resume_intelligence.local_composer import compose

records = {r["id"]: resume_corpus_seed_to_accomplishment(r) for r in json.loads((ROOT / "data/resume-corpus-initial.json").read_text(encoding="utf-8"))}
for story in json.loads((ROOT / "data/interview-story-corpus.json").read_text(encoding="utf-8")):
    key = STORY_TO_ACCOMPLISHMENT.get(story["id"], story["id"])
    records[key] = _apply(records.get(key, {"id": key}), story)
for attempt in range(3):
    start = time.perf_counter()
    result = compose(list(records.values()), "Required: Kubernetes infrastructure and reliable distributed systems.\nResponsibilities: Design deployment automation and mentor engineers.\nPreferred: Python and AWS.", "Senior Platform Engineer")
    print(json.dumps({"run": attempt + 1, "seconds": round(time.perf_counter() - start, 4), "records": len(records), "selected": len(result["resumeBullets"]), "modelCalls": 0}))
