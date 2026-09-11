"""The guard that stops Gemini writing something the candidate cannot back up.

A cloud model with a job description in front of it is under constant pressure
to be helpful, and the most helpful-looking thing it can do is claim the
candidate has the technology the posting asks for. That claim goes onto a real
application, so it is checked here rather than trusted.

The rule is deliberately one-directional. Gemini may **select** and **rephrase**
evidence that already exists in the candidate's corpus; it may not **introduce**
anything. So the check is not "does this read well" but "is every technology and
every number in this sentence already somewhere in the candidate's own
documents". Anything that fails is not repaired - it is discarded, and the
caller falls back. A silently repaired fabrication is still a fabrication.

Two things are checked, because they are the two ways a generated answer goes
wrong in practice:

* **Technologies.** Checked against `story_index`'s controlled vocabulary rather
  than against every capitalised word, so ordinary prose does not trip it and a
  named technology cannot slip past as prose.
* **Figures.** Any number that is not already in the corpus is an invented
  metric. This reuses the same normalisation the resume tailoring guard uses, so
  "$28M" and "28 M" are one claim and "K8s" does not contribute the figure 8.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("careeros.gemini.grounding")

#: Numbers that are never a claim about the candidate's experience: a year, a
#: small ordinal in ordinary prose ("one of two services"), a percentage of
#: nothing. Years are the important one - a posting-aware answer naturally says
#: "since 2019", and the corpus contains the employment dates anyway.
_INNOCUOUS_FIGURES = re.compile(r"^(?:19|20)\d{2}$")


@dataclass
class Corpus:
    """Everything the candidate can actually evidence, in lookup-friendly form."""

    text: str = ""
    technologies: frozenset[str] = frozenset()
    figures: frozenset[str] = frozenset()
    #: Fingerprint of the corpus, for cache keys. Changing the resume must
    #: invalidate every cached answer that was grounded in the old one.
    version: str = ""

    @property
    def empty(self) -> bool:
        return not self.text.strip()


@dataclass
class GroundingVerdict:
    ok: bool
    unsupported_technologies: list[str] = field(default_factory=list)
    invented_figures: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        parts = []
        if self.unsupported_technologies:
            parts.append("unsupported technologies: " + ", ".join(self.unsupported_technologies[:5]))
        if self.invented_figures:
            parts.append("invented figures: " + ", ".join(self.invented_figures[:5]))
        return "; ".join(parts)


def figure_set(text: str) -> set[str]:
    """The figures a piece of text claims, normalised.

    Shares its rules with the resume tailoring guard: strip markup, ignore
    digits that live inside a word (K8s, Log4j, S3), and treat "28M", "$28 M"
    and "28m" as one claim.
    """
    plain = re.sub(r"<[^>]+>", " ", text or "")
    found: set[str] = set()
    for match in re.finditer(r"(?<![A-Za-z0-9])(\d[\d,.]*)\s*([KkMmBb%])?(?![A-Za-z])", plain):
        digits = match.group(1).replace(",", "").rstrip(".")
        if not digits:
            continue
        found.add(f"{digits}{(match.group(2) or '').lower()}")
    return found


def _technologies(text: str) -> set[str]:
    """Named technologies in `text`, using the shared controlled vocabulary."""
    try:
        from app.services.story_index import extract_tags

        return set(extract_tags(text or "").get("technologies") or set())
    except Exception:  # noqa: BLE001 - the corpus module is optional at runtime
        logger.debug("story_index unavailable; technology grounding is skipped", exc_info=True)
        return set()


def build_corpus(
    profile: dict[str, Any] | None = None,
    *,
    resume_text: str = "",
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
    extra: str = "",
) -> Corpus:
    """Assemble everything the candidate can evidence into one searchable blob.

    The breadth matters as much as the guard itself. Built from the two-page
    resume alone, this corpus held 47 technologies and rejected a perfectly
    true sentence about Kubernetes, because a resume is a summary and the
    evidence behind it lives in the accomplishment corpus. A guard that rejects
    true statements is not a stricter guard, it is a broken one - it pushes
    every answer to the fallback and the layer stops being worth having.

    So callers that pass nothing get `load_default_corpus()`, which is the
    candidate's whole verified evidence base.
    """
    import hashlib

    parts: list[str] = [resume_text or "", extra or ""]

    if documents is not None:
        try:
            from app.services.application_assistant.candidate_match_context import (
                extract_resume_text,
            )

            parts.append(extract_resume_text(documents) or "")
        except Exception:  # noqa: BLE001
            logger.debug("Could not extract resume text for grounding", exc_info=True)

    for value in (profile or {}).values():
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value if isinstance(item, (str, int, float)))
        elif isinstance(value, dict):
            parts.extend(str(item) for item in value.values() if isinstance(item, (str, int, float)))

    for accomplishment in accomplishments or []:
        if isinstance(accomplishment, dict):
            for value in accomplishment.values():
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, (list, tuple)):
                    parts.extend(str(item) for item in value if isinstance(item, (str, int, float)))

    text = "\n".join(part for part in parts if part).strip()
    return Corpus(
        text=text,
        technologies=frozenset(_technologies(text)),
        figures=frozenset(figure_set(text)),
        version=hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:16],
    )


def check(answer: str, corpus: Corpus) -> GroundingVerdict:
    """Is every technology and figure in `answer` already in `corpus`?

    An empty corpus returns "not ok" rather than "nothing to check": with no
    evidence to ground against, there is no basis for submitting a generated
    claim on the candidate's behalf.
    """
    if not (answer or "").strip():
        return GroundingVerdict(ok=False)
    if corpus.empty:
        return GroundingVerdict(ok=False, unsupported_technologies=["<no candidate corpus loaded>"])

    lowered = corpus.text.lower()
    unsupported = sorted(
        tech for tech in _technologies(answer)
        if tech not in corpus.technologies and tech.lower() not in lowered
    )
    invented = sorted(
        figure for figure in figure_set(answer)
        if figure not in corpus.figures and not _INNOCUOUS_FIGURES.match(figure)
    )
    verdict = GroundingVerdict(
        ok=not unsupported and not invented,
        unsupported_technologies=unsupported,
        invented_figures=invented,
    )
    if not verdict.ok:
        logger.warning("Discarding a Gemini answer that was not grounded: %s", verdict.reason)
    return verdict


#: The assembled corpus, kept between calls. Reading documents and every
#: accomplishment out of SQLite and re-extracting tags costs more than the
#: Gemini call it guards, and this runs on every answered question.
_default_cache: tuple[str, Corpus] | None = None


def load_default_corpus(*, refresh: bool = False) -> Corpus:
    """The candidate's full verified evidence: profile, documents, accomplishments.

    Cached on the fingerprint of its own inputs, so editing the resume or adding
    an accomplishment produces a new corpus - and, because the corpus version is
    part of every Gemini cache key, invalidates the answers grounded in the old
    one.
    """
    global _default_cache

    try:
        from app.db.store import session_scope
        from app.services.application_assistant.candidate_match_context import (
            load_match_context,
        )

        # The same three things the matcher grounds itself in, so the guard and
        # the scorer cannot disagree about what the candidate can evidence.
        with session_scope() as db:
            profile, documents, accomplishments = load_match_context(db)
    except Exception:  # noqa: BLE001 - no database is not a reason to raise
        logger.debug("Could not load the candidate corpus", exc_info=True)
        return Corpus()

    fingerprint = f"{len(documents)}:{len(accomplishments)}:{len(profile)}"
    if not refresh and _default_cache and _default_cache[0] == fingerprint:
        return _default_cache[1]

    corpus = build_corpus(profile, documents=documents, accomplishments=accomplishments)
    _default_cache = (fingerprint, corpus)
    return corpus
