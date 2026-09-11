"""Output schemas for every Gemini task, and the versions that key their caches.

Each task has exactly one schema. Gemini is asked to honour it through
`response_format: json_schema` with `strict: true`, and the reply is re-checked
against the same object afterwards - the schema here is both the request and
the acceptance test, so the two can never drift apart.

`*_VERSION` is part of the cache key. Bump it whenever the schema or the prompt
that goes with it changes, or postings judged under the old prompt will keep
returning answers to a question that is no longer being asked.
"""

from __future__ import annotations

from typing import Any

ROLE_FAMILIES = [
    "backend", "frontend", "platform", "infrastructure", "sre", "mobile",
    "data", "ml", "security", "fullstack", "embedded", "qa", "other",
]


# ── 1. Application questions ─────────────────────────────────────────────────

APPLICATION_QUESTION_VERSION = "v1"

APPLICATION_QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        # The model naming its own evidence is what makes the grounding check
        # auditable rather than a black box: a claim with no cited evidence is
        # visible as such before the grounding guard even runs.
        "evidence": {"type": "array", "items": {"type": "string"}},
        "supported": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["answer", "evidence", "supported", "confidence", "reason"],
}

APPLICATION_QUESTION_SYSTEM = """You write one answer to a job application question, \
as the candidate, using only the candidate material provided.

Hard rules, in order of importance:

1. Every technology, employer, product, metric and duration in your answer must \
appear in the candidate material below. If it is not there, you may not write it. \
Do not infer a technology from a related one. Do not estimate years of experience.
2. If the material does not support an answer, set "supported": false and leave \
"answer" empty. An honest refusal is always better than a plausible invention.
3. "evidence" lists the exact phrases from the candidate material that back each \
claim you made. If you cannot fill it, you are not grounded.

Style: write as a real software engineer typing into a form. First person, \
2 to 4 sentences, 40 to 100 words, plain professional English. Answer the \
question directly and lead with the strongest relevant evidence.

Never use em dashes. Avoid "passionate", "extensive experience", "proven track \
record", "spearheaded", "leveraged", "robust", "cutting-edge", "seamlessly", \
"Additionally", "Furthermore", "Moreover". Do not open every answer the same way.

"confidence" is how well the candidate material supports the answer, not how \
well-written it is."""


# ── 2. Resume tailoring ──────────────────────────────────────────────────────

RESUME_TAILORING_VERSION = "v1"

RESUME_TAILORING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "bullets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "text": {"type": "string"},
                    "changed": {"type": "boolean"},
                },
                "required": ["index", "text", "changed"],
            },
        },
    },
    "required": ["bullets"],
}

RESUME_TAILORING_SYSTEM = """You re-word existing resume bullets so they speak to a \
specific job description. You are an editor, not an author.

You may: reorder the clauses in a bullet, lead with the part the posting cares \
about, replace a vague verb with a precise one, and use the posting's own word \
for a thing the bullet already describes.

You may not: add a technology, product, employer, responsibility, outcome or \
number that is not already in the bullet you were given. You may not make a \
bullet claim more scope, more seniority or more impact than it already claims. \
A bullet you cannot improve honestly is returned unchanged with "changed": false.

Every returned bullet keeps its original "index" and stays within roughly the \
same length. Return one entry per bullet you were given, in the order given."""


# ── 3. Ambiguous job matching ────────────────────────────────────────────────

AMBIGUOUS_MATCH_VERSION = "v1"

AMBIGUOUS_MATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["APPLY", "REVIEW", "SKIP"]},
        "primary_role_family": {"type": "string", "enum": ROLE_FAMILIES},
        "secondary_role_family": {"type": "string", "enum": [*ROLE_FAMILIES, ""]},
        "seniority_match": {"type": "boolean"},
        "critical_mismatch": {"type": "boolean"},
        "critical_requirements": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": [
        "decision", "primary_role_family", "secondary_role_family",
        "seniority_match", "critical_mismatch", "critical_requirements",
        "confidence", "reason",
    ],
}

AMBIGUOUS_MATCH_SYSTEM = """You are resolving a job posting that CareerOS's own \
deterministic matcher could not classify confidently. Judge from the described \
work and the candidate material.

decision:
  APPLY  - the described work is the kind of engineering this candidate does, at \
a compatible level, with no requirement they plainly cannot meet
  REVIEW - plausible but genuinely uncertain, or the posting does not describe \
the work clearly enough to judge
  SKIP   - a different kind of engineering, an incompatible level, or a \
requirement the candidate cannot meet

primary_role_family / secondary_role_family: the shape of the work. Use \
secondary only when the posting genuinely spans two; otherwise "".

critical_requirements: must-haves the posting states that the candidate material \
does not evidence. Empty when there are none.

confidence: 0..1, how clearly the posting supports your decision. Be low when the \
posting is short, generic, or does not describe the work.

reason: one factual sentence naming the deciding evidence.

Judge the work, not the writing quality. A vague posting is REVIEW with low \
confidence, never SKIP. Never assume the candidate has experience the material \
does not show."""


# ── 4. Offline benchmark labelling (MatchLab teacher) ────────────────────────

TEACHER_VERSION = "v1"

TEACHER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["APPLY", "REVIEW", "SKIP"]},
        "primary_role_family": {"type": "string", "enum": ROLE_FAMILIES},
        "secondary_role_family": {"type": "string", "enum": [*ROLE_FAMILIES, ""]},
        "seniority_match": {"type": "boolean"},
        "critical_mismatch": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": [
        "decision", "primary_role_family", "secondary_role_family",
        "seniority_match", "critical_mismatch", "confidence", "reason",
    ],
}

TEACHER_SYSTEM = """You judge whether a candidate should apply to a job, from the \
job's description only. You are never shown the job title; judge from the \
described work.

decision:
  APPLY  - the described work is the kind of engineering this candidate does, at a \
compatible level, with no requirement they plainly cannot meet
  REVIEW - plausible but uncertain, or the description is too vague to judge
  SKIP   - a different kind of engineering, an incompatible level, or a \
requirement the candidate clearly cannot meet

primary_role_family / secondary_role_family: the shape of the work described. \
Use secondary when the job genuinely spans two, otherwise "".

seniority_match: does the described level fit a senior engineer with ~9 years?
critical_mismatch: is there a must-have requirement the candidate cannot evidence?
confidence: 0..1, how clearly the description supports your decision. Low when \
the posting is short, generic, or does not describe the work.
reason: one sentence, factual, naming the deciding evidence.

Judge the work, not the writing. A vague posting is REVIEW with low confidence, \
not SKIP."""
