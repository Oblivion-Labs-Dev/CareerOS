"""Optional local CPU sentence-embedding scorer for paraphrase-aware retrieval.

Uses sentence-transformers/all-MiniLM-L6-v2 (384-dim), CPU only. Model weights
must already be present in the local Hugging Face cache (or reachable once at
warm-up); no network call is made from a resume request. If the package or the
cached weights are unavailable for any reason, every function here degrades to
returning None and callers fall back to BM25 + skill-taxonomy matching alone -
see local_composer.compose. This module never blocks resume generation on a
missing model.

Embeddings are cached per (accomplishment revision hash, exact text) so a
repeated composition over the same evidence - the common case, since the same
~50-record corpus is re-scored against a new job description each time, and
the one-page-fit loop in resume_studio recomposes several times per request -
never re-runs the model.
"""
from __future__ import annotations

import hashlib
import os
import threading
from functools import lru_cache

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_CACHE_LIMIT = 4096

_lock = threading.Lock()
_cache: dict[str, tuple[float, ...]] = {}


@lru_cache(maxsize=1)
def _model():
    try:
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(MODEL_NAME, device="cpu", local_files_only=True)
    except Exception:
        return None


def is_available() -> bool:
    return _model() is not None


def cache_key(revision: str, text: str) -> str:
    return f"{revision}:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"


def embed_many(items: list[tuple[str, str]]) -> dict[str, tuple[float, ...]] | None:
    """items: (revision, text) pairs. Returns cache_key -> unit-normalized embedding,
    or None if the model is unavailable (callers must treat this as "skip semantic
    ranking," never as an error).
    """
    model = _model()
    if model is None:
        return None

    result: dict[str, tuple[float, ...]] = {}
    to_encode_text: list[str] = []
    to_encode_key: list[str] = []
    with _lock:
        for revision, text in items:
            key = cache_key(revision, text)
            cached = _cache.get(key)
            if cached is not None:
                result[key] = cached
            elif key not in to_encode_key:
                to_encode_text.append(text)
                to_encode_key.append(key)

    if to_encode_text:
        vectors = model.encode(
            to_encode_text, batch_size=32, show_progress_bar=False, normalize_embeddings=True
        )
        with _lock:
            for key, vector in zip(to_encode_key, vectors, strict=True):
                packed = tuple(float(v) for v in vector)
                if len(_cache) >= _CACHE_LIMIT:
                    _cache.pop(next(iter(_cache)))
                _cache[key] = packed
                result[key] = packed
    return result


def cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Both vectors are already unit-normalized, so the dot product is the cosine similarity."""
    return sum(x * y for x, y in zip(a, b, strict=True))
