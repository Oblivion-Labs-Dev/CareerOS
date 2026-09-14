"""Okapi BM25 over pre-tokenized documents. Pure Python, deterministic, no
external dependency - the candidate pool is small enough (tens of documents)
that this never needs a vectorized implementation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

DEFAULT_K1 = 1.5
DEFAULT_B = 0.75


@dataclass
class BM25Index:
    k1: float = DEFAULT_K1
    b: float = DEFAULT_B
    _doc_term_counts: list[dict[str, int]] = field(default_factory=list)
    _doc_lengths: list[int] = field(default_factory=list)
    _avg_length: float = 0.0
    _idf: dict[str, float] = field(default_factory=dict)

    @classmethod
    def build(cls, documents: list[tuple[str, ...]], *, k1: float = DEFAULT_K1, b: float = DEFAULT_B) -> BM25Index:
        index = cls(k1=k1, b=b)
        for tokens in documents:
            counts: dict[str, int] = {}
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
            index._doc_term_counts.append(counts)
            index._doc_lengths.append(len(tokens))
        n = len(documents)
        index._avg_length = (sum(index._doc_lengths) / n) if n else 0.0
        document_frequency: dict[str, int] = {}
        for counts in index._doc_term_counts:
            for term in counts:
                document_frequency[term] = document_frequency.get(term, 0) + 1
        # BM25's standard idf variant; floors at ~0 for terms in every document
        # rather than going negative, since a near-universal term should never
        # actively penalize a candidate.
        index._idf = {
            term: max(0.0, math.log(1 + (n - freq + 0.5) / (freq + 0.5)))
            for term, freq in document_frequency.items()
        }
        return index

    def score(self, query_tokens: tuple[str, ...], doc_index: int) -> float:
        counts = self._doc_term_counts[doc_index]
        length = self._doc_lengths[doc_index] or 1
        avg = self._avg_length or 1.0
        total = 0.0
        for term in set(query_tokens):
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            idf = self._idf.get(term, 0.0)
            denominator = frequency + self.k1 * (1 - self.b + self.b * length / avg)
            total += idf * (frequency * (self.k1 + 1)) / (denominator or 1.0)
        return total

    def score_all(self, query_tokens: tuple[str, ...]) -> list[float]:
        return [self.score(query_tokens, i) for i in range(len(self._doc_term_counts))]

    def rank(self, query_tokens: tuple[str, ...]) -> list[int]:
        """Document indices ordered best-first; ties break on original index for determinism."""
        scores = self.score_all(query_tokens)
        return sorted(range(len(scores)), key=lambda i: (-scores[i], i))
