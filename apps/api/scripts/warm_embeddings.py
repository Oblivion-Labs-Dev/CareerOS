"""Download the sentence-embedding weights so request paths never need the network.

`resume_intelligence.semantic` loads with `local_files_only=True` on purpose: a
resume request must not block on a model download, and must not quietly reach
the internet. That makes fetching the weights a separate, deliberate step, and
this is it.

    apps/api/.venv/Scripts/python scripts/warm_embeddings.py          # configured model
    apps/api/.venv/Scripts/python scripts/warm_embeddings.py --all    # every supported model

Both supported models are ~90-130MB and 384-dimensional. Having both cached is
what lets the retrieval bench compare them, and what lets
CAREEROS_EMBEDDING_MODEL be flipped without a download.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.resume_intelligence.semantic import MODELS, model_name  # noqa: E402


def fetch(name: str) -> bool:
    print(f"fetching {name} ...", flush=True)
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(name, device="cpu")
        dimensions = model.get_embedding_dimension() if hasattr(model, "get_embedding_dimension") else model.get_sentence_embedding_dimension()
        print(f"  ready: {name} ({dimensions} dimensions)", flush=True)
        return True
    except Exception as exc:  # noqa: BLE001 - report and carry on to the next model
        print(f"  FAILED: {name}: {type(exc).__name__}: {exc}", flush=True)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="fetch every supported model")
    args = parser.parse_args()
    targets = [name for name, _ in MODELS.values()] if args.all else [model_name()]
    return 0 if all(fetch(name) for name in targets) else 1


if __name__ == "__main__":
    raise SystemExit(main())
