"""Hiding the job title before a posting is sent for benchmark labelling.

Lives in `app` rather than in the MatchLab scripts because both the offline
study and the production gateway need exactly the same redaction. Two copies
that drift apart would mean labels produced on different terms being compared
as though they were the same.

Omitting the `title` field is not enough. Postings repeat the title as a
heading, in the opening line, and in the "About the role" paragraph, so a
teacher that never sees the title field still reads it three times. Both the
exact title and its distinctive part are removed - "Engine Systems" leaks the
role family as effectively as "Senior Engine Systems Engineer" does.
"""

from __future__ import annotations

import re

_NOISE = re.compile(
    r"\b(senior|staff|principal|lead|sr|junior|associate|"
    r"software|engineer|engineering|developer|i{1,3}|\d+)\b",
    re.I,
)


def _looks_like_heading(line: str) -> bool:
    words = line.strip().split()
    if not words:
        return False
    capitalised = sum(1 for word in words if word[:1].isupper())
    return capitalised >= max(1, len(words) // 2)


def strip_title(title: str, body: str) -> tuple[str, int]:
    """Remove the job title from the body. Returns (redacted body, redactions)."""
    redacted = body
    count = 0

    targets = [title.strip()]
    distinctive = _NOISE.sub(" ", title)
    distinctive = re.sub(r"[^\w\s/&+-]", " ", distinctive)
    distinctive = re.sub(r"\s{2,}", " ", distinctive).strip(" ,-–—|/")
    if len(distinctive) >= 4:
        targets.append(distinctive)

    for target in targets:
        if len(target) < 4:
            continue
        pattern = re.compile(re.escape(target).replace(r"\ ", r"[\s\-]+"), re.I)
        redacted, hits = pattern.subn("[ROLE TITLE REDACTED]", redacted)
        count += hits

    # A short heading-like opening line is the title even when the strings did
    # not match exactly - postings rewrite it ("Engineer, Platform" against a
    # title of "Platform Engineer") often enough to matter.
    lines = redacted.splitlines()
    while lines and (not lines[0].strip() or (
        len(lines[0].strip()) < 70
        and not lines[0].strip().endswith((".", ":", ";"))
        and len(lines[0].split()) <= 9
        and "REDACTED" not in lines[0]
        and _looks_like_heading(lines[0])
    )):
        if lines[0].strip():
            count += 1
        lines.pop(0)
    return "\n".join(lines).strip(), count
