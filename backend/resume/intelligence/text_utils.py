"""Shared text utilities for resume intelligence."""

from __future__ import annotations

import re

STOP_WORDS = {
    "and", "the", "with", "for", "you", "will", "our", "that", "this", "have", "from",
    "are", "was", "been", "being", "your", "all", "can", "may", "must", "should",
    "would", "about", "into", "through", "during", "before", "after", "each", "other",
    "some", "such", "than", "too", "very", "just", "also", "any", "able", "work",
    "team", "role", "job", "experience", "years", "year", "using", "use", "used",
}


def extract_keywords(text: str, *, limit: int = 40) -> list[str]:
    words = re.findall(r"[a-z][a-z0-9+#.-]{2,}", text.lower())
    seen: set[str] = set()
    out: list[str] = []
    for word in words:
        if word in STOP_WORDS or word in seen:
            continue
        seen.add(word)
        out.append(word)
        if len(out) >= limit:
            break
    return out


def normalize_skill(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def text_blob(parts: list[str | None | list[str]]) -> str:
    flat: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, list):
            flat.extend(str(item) for item in part if item)
        elif part:
            flat.append(str(part))
    return " ".join(flat).lower()
