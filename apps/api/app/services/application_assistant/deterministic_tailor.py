"""Tailor a resume to a posting without a language model.

The local models proved weak at rewriting these bullets: measured, they echoed
most of them back unchanged, occasionally returned them in the wrong slots, and
the best rewrite moved one job 52.5% -> 58.1%. This does the part of tailoring
that is genuinely mechanical, deterministically, in milliseconds, and does not
attempt the part that is not.

What it does: when a posting and a bullet refer to the same thing by different
names, it makes the bullet use the posting's name for it. A resume saying "IaC"
and a posting asking for "infrastructure as code" are talking about the same
work, and an automated reader may not know that.

What it deliberately does not do: write prose, merge bullets, or add skills. A
bullet's facts are fixed.

The danger this design exists to avoid
--------------------------------------
The obvious implementation is to reuse story_index's alias table, which already
maps many surface forms to one canonical tag. That would fabricate. Those
aliases are *retrieval* equivalences - they answer "is this posting about
Kubernetes", where "EKS" and "container orchestration" both count. They are not
interchangeable *claims*:

    Kubernetes -> eks, aks, gke     writing "EKS" when the work was AKS is false
    Kafka      -> msk               asserts AWS-managed Kafka specifically
    RAG        -> vector search      the candidate's own notes say, verbatim,
                                     "Do not claim you had a vector database
                                     unless you actually did"

So substitution runs off a separate, deliberately small table of pairs that are
the *same words* - an abbreviation and its expansion. Those can be swapped in
either direction without changing what is being claimed. Anything requiring
judgement about whether two technologies are equivalent is not in this table and
should not be added to it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Pairs that are the same claim written two ways. Each entry is
#: (canonical form, alternate form). Both directions are safe because neither
#: form asserts anything the other does not - they are spelling variants, not
#: related technologies.
SAFE_SYNONYMS: tuple[tuple[str, str], ...] = (
    ("Kubernetes", "K8s"),
    ("infrastructure as code", "IaC"),
    ("continuous integration and delivery", "CI/CD"),
    ("machine learning", "ML"),
    ("retrieval augmented generation", "RAG"),
    ("site reliability engineering", "SRE"),
    ("role-based access control", "RBAC"),
    ("data loss prevention", "DLP"),
    ("service level objective", "SLO"),
    ("transactions per second", "TPS"),
    ("proof of concept", "POC"),
    ("continuous integration", "CI"),
    ("continuous delivery", "CD"),
    ("large language model", "LLM"),
    ("application programming interface", "API"),
    ("single sign-on", "SSO"),
    ("identity and access management", "IAM"),
    ("disaster recovery", "DR"),
    ("high availability", "HA"),
)


def _word_pattern(form: str) -> re.Pattern[str]:
    escaped = re.escape(form).replace(r"\ ", r"[\s\-]+")
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)


def _plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", str(text or ""))


@dataclass
class AlignmentResult:
    bullets: list[str]
    substitutions: list[dict[str, Any]] = field(default_factory=list)
    skipped_for_length: int = 0

    @property
    def changed(self) -> int:
        return len({s["bullet"] for s in self.substitutions})


def align_to_posting(
    bullets: list[str],
    job_text: str,
    *,
    length_budget: int = 20,
) -> AlignmentResult:
    """Rewrite each bullet to use the posting's wording for things it already says.

    A substitution happens only when all of these hold:
      * the bullet already contains one form of a safe synonym pair;
      * the posting uses the *other* form;
      * the result still fits the bullet's slot.

    The last condition matters because the rendered PDF overlays each bullet
    into a fixed-height slot, and an expansion like IaC -> infrastructure as
    code is 20 characters longer. Overflowing the slot to gain a keyword is a
    bad trade, so those substitutions are dropped rather than applied.
    """
    result = AlignmentResult(bullets=list(bullets))
    posting = str(job_text or "")

    for index, bullet in enumerate(result.bullets):
        budget = len(_plain(bullets[index])) + length_budget
        working = bullet

        for canonical, alternate in SAFE_SYNONYMS:
            canon_re, alt_re = _word_pattern(canonical), _word_pattern(alternate)
            in_posting_canonical = bool(canon_re.search(posting))
            in_posting_alternate = bool(alt_re.search(posting))

            # The posting has to prefer one form and not the other, or there is
            # nothing to align to.
            if in_posting_canonical == in_posting_alternate:
                continue

            want, have_re = (
                (canonical, alt_re) if in_posting_canonical else (alternate, canon_re)
            )
            match = have_re.search(working)
            if not match:
                continue

            candidate = working[: match.start()] + want + working[match.end():]
            if len(_plain(candidate)) > budget:
                result.skipped_for_length += 1
                continue

            result.substitutions.append({
                "bullet": index + 1,
                "from": match.group(0),
                "to": want,
            })
            working = candidate

        result.bullets[index] = working

    return result


def tailor(
    master_bullets: list[str],
    title: str,
    description: str,
    *,
    length_budget: int = 20,
) -> dict[str, Any]:
    """Deterministically tailor a resume to one posting. No model, no network."""
    posting = f"{title}\n{description}"
    aligned = align_to_posting(master_bullets, posting, length_budget=length_budget)

    try:
        from app.services.story_index import flat_tags

        requirements = sorted(flat_tags(posting))
    except Exception:  # noqa: BLE001
        requirements = []

    return {
        "bullets": aligned.bullets,
        "changed": aligned.changed,
        "substitutions": aligned.substitutions,
        "skippedForLength": aligned.skipped_for_length,
        "requirements": requirements,
        "method": "deterministic",
    }
