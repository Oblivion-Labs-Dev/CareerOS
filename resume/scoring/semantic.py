"""Optional local CPU sentence-embedding scorer for paraphrase-aware retrieval.

CPU only, and the weights must already be in the local Hugging Face cache: no
network call is ever made from a resume request. If the package or the cached
weights are unavailable for any reason, every function here degrades to
returning None and callers fall back to BM25 + skill-taxonomy matching alone -
see local_composer.compose. This module never blocks resume generation on a
missing model.

Two models are supported and the choice is one environment variable:

    CAREEROS_EMBEDDING_MODEL=minilm  sentence-transformers/all-MiniLM-L6-v2  (default)
    CAREEROS_EMBEDDING_MODEL=bge     BAAI/bge-small-en-v1.5

Both are 384-dimensional and about 90-130MB, so switching costs nothing in
memory or storage, and a cached embedding from one is never mistaken for the
other because the model id and direction are part of the cache key.

**MiniLM is the default because it measured better, not because it was here
first.** BGE-small scores far above MiniLM on public retrieval leaderboards and
was expected to win, so it was made the default and then benchmarked.
`scripts/matchlab/evidence_retrieval.py` over 241 labelled requirement queries:

    retriever   p@1     MAP    nDCG@10   MRR
    minilm      0.560   0.454  0.466     0.671
    bm25        0.465   0.413  0.388     0.584
    bge         0.419   0.388  0.375     0.565

BGE came out *below plain BM25* on this task. The plausible reason is task
shape: the leaderboards it wins are short-query-against-long-passage search,
while this is one short sentence (a requirement) against another short sentence
(a resume bullet), which is much closer to symmetric similarity - the thing
MiniLM was trained for. BGE stays supported and one variable away, because the
right model is an empirical question that a larger corpus could answer
differently; re-run the bench before changing this line.

**BGE needs its query instruction.** The bge-*-en-v1.5 models were trained with
an asymmetric convention: a *query* is prefixed with "Represent this sentence
for searching relevant passages: " and a *passage* is embedded bare. Embedding
both sides bare, which is the obvious thing to do and what a drop-in swap would
have done, throws away a measurable part of the model's retrieval quality. So
the two directions are separate functions here rather than one, and the
distinction is in the caller's hands where it belongs: a job requirement is a
query, a resume bullet is a passage.

Embeddings are cached per (model, revision hash, exact text) so a repeated
composition over the same evidence - the common case, since the same ~50-record
corpus is re-scored against a new job description each time - never re-runs the
model.
"""
from __future__ import annotations

import hashlib
import os
import threading
from functools import lru_cache

#: model key -> (hugging face id, query instruction or "")
MODELS: dict[str, tuple[str, str]] = {
    "bge": (
        "BAAI/bge-small-en-v1.5",
        "Represent this sentence for searching relevant passages: ",
    ),
    "minilm": ("sentence-transformers/all-MiniLM-L6-v2", ""),
}

DEFAULT_MODEL_KEY = "minilm"
_CACHE_LIMIT = 4096

_lock = threading.Lock()
_cache: dict[str, tuple[float, ...]] = {}


def model_key() -> str:
    """Which embedding model this process should use."""
    requested = (os.environ.get("CAREEROS_EMBEDDING_MODEL") or DEFAULT_MODEL_KEY).strip().lower()
    return requested if requested in MODELS else DEFAULT_MODEL_KEY


def model_name() -> str:
    return MODELS[model_key()][0]


def query_instruction() -> str:
    return MODELS[model_key()][1]


@lru_cache(maxsize=4)
def _load(name: str):
    try:
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(name, device="cpu", local_files_only=True)
    except Exception:
        return None


def _model():
    """The configured model, or the other one if only that is cached.

    Falling back matters because the default changed: an installation that has
    only MiniLM cached must keep working rather than silently losing semantic
    ranking altogether.
    """
    model = _load(model_name())
    if model is not None:
        return model
    for key, (name, _instruction) in MODELS.items():
        if key != model_key():
            fallback = _load(name)
            if fallback is not None:
                return fallback
    return None


def is_available() -> bool:
    return _model() is not None


def active_model_name() -> str | None:
    """Which model is actually loaded, for diagnostics and the bench report.

    This is the configured one unless it was not cached and the other was, so
    it is the only honest answer to "what produced these scores".
    """
    if _load(model_name()) is not None:
        return model_name()
    for key, (name, _instruction) in MODELS.items():
        if key != model_key() and _load(name) is not None:
            return name
    return None


#: The two directions text can be embedded in. They are part of the cache
#: identity, not just a formatting detail: with a query instruction applied,
#: the same sentence has two different embeddings, and keying only on the text
#: means whichever direction ran first silently wins. That is not theoretical —
#: it made an instructed-versus-bare BGE comparison return byte-identical
#: numbers for both arms, because the second arm read the first arm's vectors
#: straight out of the cache.
PASSAGE = "passage"
QUERY = "query"


def cache_key(revision: str, text: str, role: str = PASSAGE) -> str:
    """Identity of one embedding.

    The model key is included because a MiniLM vector and a BGE vector for the
    same sentence are not interchangeable - cosine between them is meaningless.
    The role is included for the same reason.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{model_key()}:{role}:{revision}:{digest}"


def _embed(items: list[tuple[str, str]], role: str) -> dict[str, tuple[float, ...]] | None:
    model = _model()
    if model is None:
        return None
    instruction = query_instruction() if role == QUERY else ""

    result: dict[str, tuple[float, ...]] = {}
    to_encode_text: list[str] = []
    to_encode_key: list[str] = []
    with _lock:
        for revision, text in items:
            key = cache_key(revision, text, role)
            cached = _cache.get(key)
            if cached is not None:
                result[key] = cached
            elif key not in to_encode_key:
                to_encode_text.append(instruction + text)
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


def embed_many(items: list[tuple[str, str]]) -> dict[str, tuple[float, ...]] | None:
    """Embed passages - resume bullets, stories, anything being searched over.

    items: (revision, text) pairs. Returns cache_key -> unit-normalized
    embedding, or None if no model is available (callers must treat that as
    "skip semantic ranking", never as an error). Look results up with
    `cache_key(revision, text)`.
    """
    return _embed(items, PASSAGE)


def embed_queries(items: list[tuple[str, str]]) -> dict[str, tuple[float, ...]] | None:
    """Embed queries - job requirements, the thing being searched *for*.

    Identical to `embed_many` except that a model with a query instruction gets
    it applied. Look results up with `cache_key(revision, text, semantic.QUERY)`.
    """
    return _embed(items, QUERY)


def cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Both vectors are already unit-normalized, so the dot product is the cosine similarity."""
    return sum(x * y for x, y in zip(a, b, strict=True))
