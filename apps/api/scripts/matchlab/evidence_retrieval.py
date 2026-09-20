"""Precision and recall for *evidence retrieval*, the step resume tailoring rests on.

The rest of matchlab grades one question: should this posting be applied to at
all. This module grades a different one, and it is the one the resume builder
depends on: **given a requirement in a posting, does the retriever put the
resume evidence that genuinely supports it at the top?**

That question needed measuring because the answer was assumed. The builder
ranked evidence with BM25 fused with a MiniLM bi-encoder and nobody had ever
checked whether the semantic half helped, hurt, or did nothing — and a bullet
about Microsoft Defender was credited with a distributed-systems requirement on
the shared words "backend" and "systems", which is the sort of thing a precision
number makes impossible to miss.

Granularity
-----------
One **query per requirement**, not per posting. That is the granularity the
product retrieves at (`minimal_tailoring._rank` scores every candidate against
every requirement and sums), it gives an order of magnitude more queries from
the same postings, and "which bullet answers *this* requirement" is a question
with a defensible ground truth, where "which bullet suits this posting" is not.

Ground truth
------------
A bullet is relevant to a requirement when the **story it came from is authored
with a tag the requirement asks for**. The tags on each corpus story were
written by hand, by the candidate, about their own work; the retrievers under
test only ever see raw text. So the labels are not a restatement of what BM25 or
an embedding model computes.

Two honest caveats, both of which the report prints:

* These are *proxy* labels, not human relevance judgements. A story tagged
  "Kubernetes" may contain a bullet that says nothing about Kubernetes, which
  counts here as a relevant bullet the retriever ought to find. That inflates
  the ceiling for everyone equally, so it is sound for *comparing* retrievers
  and should not be read as an absolute quality score.
* Requirements that carry no tags are skipped, because there is nothing to
  label them against. Roughly a third of requirement lines in a real posting
  are prose with no named technology, and no retriever is credited or blamed
  for them here.

Usage
-----
    apps/api/.venv/Scripts/python scripts/matchlab/evidence_retrieval.py
    apps/api/.venv/Scripts/python scripts/matchlab/evidence_retrieval.py --models bge,minilm --postings 40
    apps/api/.venv/Scripts/python scripts/matchlab/evidence_retrieval.py --json out.json

Each embedding model is loaded, measured and released before the next one, so
only one set of weights is resident at a time.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(API_ROOT / "scripts"))

from matchlab.metrics import RetrievalReport  # noqa: E402

REPO_ROOT = API_ROOT.parent.parent
TEST_POSTINGS = REPO_ROOT / "data" / "resume-tests"


# ---------------------------------------------------------------------------
# The evaluation set
# ---------------------------------------------------------------------------

@dataclass
class Bullet:
    """One piece of resume evidence, with the story it came from."""

    text: str
    story_id: str
    authored_tags: frozenset[str]


@dataclass
class Query:
    """One requirement, with the bullets that genuinely answer it."""

    posting: str
    text: str
    tags: frozenset[str]
    relevant: frozenset[int]  # indices into the bullet list


def load_bullets() -> list[Bullet]:
    """Every candidate bullet the composer can see, with its story's authored tags.

    The haystack is deliberately the *whole* candidate set rather than the
    approved subset: retrieval quality is about ordering the corpus, and
    restricting it to what is already approved would measure a much easier
    problem than the one the builder faces.
    """
    from app.db.store import list_entities, session_scope
    from app.services.resume_intelligence.local_composer import _candidates
    from app.services.story_index import load_corpus, normalize_tag

    def authored(record: dict[str, Any]) -> frozenset[str]:
        tags: set[str] = set()
        for key in ("technologies", "concepts", "behavioural", "primary"):
            for raw in record.get(key) or []:
                canonical = normalize_tag(str(raw))
                if canonical:
                    tags.add(canonical)
        return frozenset(tags)

    # Authored tags live on the corpus file, which is the hand-written source.
    by_story = {str(s.get("id")): authored(s) for s in load_corpus()}
    with session_scope() as db:
        records = list_entities(db, "accomplishment")
    # A story synced into an accomplishment keeps the record's tag lists too;
    # fall back to those when the story is not in the file (some are DB-only).
    by_record = {str(r.get("id")): authored(r) for r in records}

    bullets: list[Bullet] = []
    seen: set[str] = set()
    for candidate in _candidates(records):
        text = candidate["optimizedBullet"]
        if text in seen:
            continue
        seen.add(text)
        story_id = str(candidate["source"].get("storyId") or candidate["id"])
        tags = by_story.get(story_id) or by_record.get(str(candidate["id"])) or frozenset()
        bullets.append(Bullet(text=text, story_id=story_id, authored_tags=tags))
    return bullets


def load_postings(limit: int) -> list[tuple[str, str]]:
    """(name, description) pairs: the hand-written test set, then real postings."""
    postings: list[tuple[str, str]] = []
    for path in sorted(TEST_POSTINGS.glob("jd-*.txt")):
        postings.append((path.stem, path.read_text(encoding="utf-8")))
    if len(postings) >= limit:
        return postings[:limit]

    from app.db.store import session_scope
    from app.services.job_discover import store as job_discover

    with session_scope() as db:
        snapshot = job_discover.get_snapshot(db)
    for job in snapshot.get("jobs") or []:
        description = str(job.get("description") or "")
        if len(description) < 1500:
            continue
        name = f"{job.get('companyName') or 'unknown'}-{job.get('id')}"
        postings.append((name, description))
        if len(postings) >= limit:
            break
    return postings


def build_queries(bullets: list[Bullet], postings: list[tuple[str, str]]) -> list[Query]:
    from app.services.resume_intelligence.evidence_match import extract_requirements
    from app.services.story_index import flat_tags

    queries: list[Query] = []
    for name, description in postings:
        for requirement in extract_requirements(description):
            tags = frozenset(flat_tags(requirement["text"]))
            if not tags:
                continue  # No ground truth available for untagged prose.
            relevant = frozenset(
                index for index, bullet in enumerate(bullets) if bullet.authored_tags & tags
            )
            if not relevant:
                continue  # Nothing in the corpus answers this; see the module docstring.
            queries.append(Query(posting=name, text=requirement["text"], tags=tags, relevant=relevant))
    return queries


# ---------------------------------------------------------------------------
# Retrievers
# ---------------------------------------------------------------------------

Ranker = Callable[[Query, list[Bullet]], list[int]]


def bm25_ranker(bullets: list[Bullet]) -> Ranker:
    """The product's lexical half, with the product's own index."""
    from app.services.resume_intelligence.bm25 import BM25Index
    from app.services.resume_intelligence.local_composer import tokenize

    index = BM25Index.build([tokenize(b.text) for b in bullets])

    def rank(query: Query, _bullets: list[Bullet]) -> list[int]:
        return index.rank(tokenize(query.text))

    return rank


def embedding_ranker(bullets: list[Bullet], *, instructed: bool = True) -> Ranker:
    """Pure cosine ranking.

    `instructed` controls whether the query side gets the model's retrieval
    instruction. It is a flag rather than an assumption because BGE's
    instruction was written for asymmetric search - a short query against a
    long passage - and a job requirement against a resume bullet is two short
    sentences, which is closer to symmetric. Whether the instruction helps here
    is an empirical question, so it is measured rather than assumed.
    """
    from app.services.resume_intelligence import semantic

    passages = semantic.embed_many([(f"b{i}", b.text) for i, b in enumerate(bullets)])
    if passages is None:
        raise RuntimeError("no embedding model available")
    vectors = [passages[semantic.cache_key(f"b{i}", b.text)] for i, b in enumerate(bullets)]
    embed_query = semantic.embed_queries if instructed else semantic.embed_many

    def rank(query: Query, _bullets: list[Bullet]) -> list[int]:
        embedded = embed_query([("q", query.text)])
        if embedded is None:
            raise RuntimeError("no embedding model available")
        vector = embedded[semantic.cache_key("q", query.text, semantic.QUERY if instructed else semantic.PASSAGE)]
        sims = [semantic.cosine(vector, other) for other in vectors]
        return sorted(range(len(bullets)), key=lambda i: (-sims[i], i))

    return rank


def fused_ranker(bullets: list[Bullet], *, instructed: bool = True) -> Ranker:
    """BM25 and the embedding model combined exactly as the product combines them.

    Reciprocal rank fusion, not a weighted sum of scores: BM25 and cosine live
    on incompatible scales and mixing them directly is how a retriever ends up
    silently dominated by whichever one has the larger numbers.
    """
    from app.services.resume_intelligence.fusion import reciprocal_rank_fusion

    lexical = bm25_ranker(bullets)
    dense = embedding_ranker(bullets, instructed=instructed)

    def rank(query: Query, all_bullets: list[Bullet]) -> list[int]:
        fused = reciprocal_rank_fusion([lexical(query, all_bullets), dense(query, all_bullets)])
        return sorted(range(len(all_bullets)), key=lambda i: (-fused.get(i, 0.0), i))

    return rank


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------

def measure(name: str, ranker: Ranker, queries: list[Query], bullets: list[Bullet]) -> RetrievalReport:
    report = RetrievalReport(name=name)
    for query in queries:
        started = time.perf_counter()
        order = ranker(query, bullets)
        report.latencies.append(time.perf_counter() - started)
        report.rankings.append([1 if index in query.relevant else 0 for index in order])
    return report


def release_models() -> None:
    from app.services.resume_intelligence import semantic

    semantic._load.cache_clear()
    semantic._cache.clear()
    gc.collect()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidence-retrieval precision and recall.")
    parser.add_argument("--models", default="bge,minilm",
                        help="comma-separated embedding models to compare (bge, minilm)")
    parser.add_argument("--postings", type=int, default=24,
                        help="how many postings to draw requirements from")
    parser.add_argument("--json", type=Path, default=None, help="write the full report here")
    args = parser.parse_args()

    bullets = load_bullets()
    postings = load_postings(args.postings)
    queries = build_queries(bullets, postings)
    print(f"evidence bullets : {len(bullets)}")
    print(f"postings         : {len(postings)}")
    print(f"labelled queries : {len(queries)}  "
          f"(median {statistics.median([len(q.relevant) for q in queries]):.0f} relevant bullets each)")
    if not queries:
        print("no labelled queries; nothing to measure")
        return 1

    summaries: list[dict[str, Any]] = []
    release_models()
    summaries.append(measure("bm25", bm25_ranker(bullets), queries, bullets).summary())

    for key in [m.strip() for m in args.models.split(",") if m.strip()]:
        from app.services.resume_intelligence import semantic

        release_models()
        os.environ["CAREEROS_EMBEDDING_MODEL"] = key
        active = semantic.active_model_name()
        if active is None:
            print(f"  {key}: no weights cached; run scripts/warm_embeddings.py --all")
            continue
        note = f"model={active}"
        if semantic.model_key() != key:
            note += " (requested model unavailable)"
        for instructed in ({True, False} if semantic.query_instruction() else {True}):
            suffix = "" if instructed else " (no instruction)"
            dense = measure(key + suffix, embedding_ranker(bullets, instructed=instructed), queries, bullets)
            dense.notes.append(note)
            summaries.append(dense.summary())
            fused = measure(f"bm25+{key}{suffix}",
                            fused_ranker(bullets, instructed=instructed), queries, bullets)
            fused.notes.append(note)
            summaries.append(fused.summary())
    release_models()

    columns = ["retriever", "p@1", "p@3", "p@5", "r@5", "r@10", "map", "ndcg@10", "mrr", "latencyMs"]
    widths = {c: max(len(c), *(len(str(s.get(c))) for s in summaries)) for c in columns}
    print()
    print("  ".join(c.rjust(widths[c]) for c in columns))
    print("  ".join("-" * widths[c] for c in columns))
    for summary in summaries:
        print("  ".join(str(summary.get(c)).rjust(widths[c]) for c in columns))
    print()
    print("Labels are proxy relevance from hand-authored story tags, so these compare")
    print("retrievers against each other; they are not absolute quality scores.")

    if args.json:
        args.json.write_text(json.dumps({
            "bullets": len(bullets), "postings": len(postings), "queries": len(queries),
            "results": summaries,
        }, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
