"""Deciding which postings are worth a Gemini call, and which are not.

This is the gate that keeps Gemini out of the normal matching path. CareerOS
has to rank hundreds of postings, and the deterministic matcher does that in
milliseconds with no model resident. Sending each one to Gemini would be slower,
quota-limited and no more correct on the cases the deterministic matcher already
gets right.

So Gemini is called only where the deterministic result is genuinely undecided.
Five signals mark that, and each one is a case where a confident-looking score
is hiding a coin flip:

* **No score at all.** An unscored posting has no deterministic opinion to
  defer to. It is not dropped - the user was explicit that a posting must never
  be discarded for being unscored - but it is a natural candidate for a second
  opinion when there is spare capacity.
* **Close to the auto-apply boundary.** A posting at 78 and one at 82 get
  opposite treatment from a difference well inside the matcher's own noise.
  That band is where a better judgement changes an outcome.
* **No clear role family.** The parser could not tell what kind of engineering
  the posting describes, which is the input everything downstream assumes.
* **Two role families in contention.** "Platform" and "data" scoring within a
  hair of each other is not a posting that spans both - it is a posting the
  keyword parser cannot read.
* **A critical requirement that cannot be checked.** Clearance, citizenship, a
  specific degree, a years-with-technology threshold: things that decide
  eligibility outright and that keyword matching routinely misreads.

Everything else is left alone. A posting the deterministic matcher scored
confidently is not sent to Gemini even when Gemini is idle and free.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

#: The match score at or above which Autopilot may apply without asking. Kept
#: here as the reference point for "near the boundary", not as a second source
#: of truth - the runner still owns the decision itself.
AUTO_APPLY_SCORE = float(80)

#: How far either side of the boundary counts as too close to call. Widening
#: this sends more postings to Gemini; it does not change any decision by
#: itself, because a Gemini failure leaves the deterministic result standing.
BOUNDARY_BAND = float(8)

#: Role-family keywords. This exists to detect *ambiguity*, not to score: the
#: production matcher is untouched. Keeping it here rather than importing the
#: MatchLab copy is deliberate - the experiment and the gate should be free to
#: disagree without one silently changing the other.
ROLE_FAMILY_SIGNALS: dict[str, tuple[str, ...]] = {
    "backend": ("backend", "back-end", "server-side", "microservice", "api development", "distributed system"),
    "frontend": ("frontend", "front-end", "react", "typescript", "css", "user interface", "browser"),
    "platform": ("platform", "developer experience", "internal tooling", "build system", "ci/cd"),
    "infrastructure": ("infrastructure", "kubernetes", "terraform", "cloud", "provisioning", "networking"),
    "sre": ("site reliability", "sre", "on-call", "incident", "observability", "uptime", "slo"),
    "mobile": ("android", "ios", "swift", "kotlin", "mobile app", "react native"),
    "data": ("data pipeline", "etl", "spark", "warehouse", "analytics", "streaming", "kafka"),
    "ml": ("machine learning", "deep learning", "model training", "llm", "inference", "pytorch"),
    "security": ("security", "cryptograph", "vulnerabilit", "threat", "appsec", "penetration"),
    "fullstack": ("full stack", "full-stack", "end to end feature", "fullstack"),
    "embedded": ("embedded", "firmware", "rtos", "device driver", "bare metal"),
    "qa": ("quality assurance", "test automation", "sdet", "manual testing"),
}

#: Requirements that decide eligibility outright and that keyword matching gets
#: wrong in both directions - claiming a match that is not there, and missing
#: one that is. When a posting states one of these, the deterministic matcher
#: cannot be trusted to have understood it.
#:
#: Kept to genuine eligibility blockers that are rare. A years-of-experience bar
#: was in this list and had to come out: measured over 400 real postings it
#: matched 140 of them, because "8+ years" appears in almost every senior
#: posting. It is also the one requirement here the deterministic matcher and
#: the profile between them *can* check, so flagging it spent an API call to be
#: told what CareerOS already knew.
CRITICAL_REQUIREMENT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"security clearance|ts/sci|top secret|polygraph", "security clearance"),
    (r"u\.?s\.? citizen|citizenship required|must be a citizen", "citizenship"),
    # `itar` needs word boundaries. Without them it matched the middle of
    # "military", and 95 of 400 real postings were flagged as export-controlled
    # because they described a defence customer.
    (r"export control|\bitar\b|\bear99\b", "export control"),
    # A doctorate only counts when it is actually required. Postings routinely
    # list it as one of several alternatives ("a bachelor's and 5 years, or a
    # master's and 3, or a PhD"), which is the opposite of a hard requirement.
    (r"\b(?:ph\.?d\.?|doctorate)\b[^.]{0,60}\brequired\b"
     r"|\brequires?\b[^.]{0,60}\b(?:ph\.?d\.?|doctorate)\b", "doctorate required"),
    (r"\b(?:master'?s|m\.s\.)\s+(?:degree\s+)?required", "master's degree required"),
    (r"active\s+(?:dod|government)\s+clearance", "government clearance"),
)

#: What turns a stated requirement into an *unclear* one.
#:
#: A flatly stated requirement is not ambiguous - the candidate either evidences
#: it or does not, and CareerOS can decide that without asking anyone. What a
#: second opinion is actually useful for is the hedged version: "clearance
#: preferred", "ability to obtain clearance", "or equivalent experience". Those
#: are judgement calls, and they are the only ones worth an API call.
#:
#: Measured over 400 real postings, requiring a hedge took this trigger from 105
#: postings to a handful.
_HEDGED_REQUIREMENT = re.compile(
    r"preferred|ability to obtain|able to obtain|eligible to obtain|"
    r"or equivalent|nice to have|a plus|desirable|willing to|"
    r"ideally|bonus points",
    re.I,
)

#: A hedge only counts when it is in the *same clause* as the requirement.
#: A fixed character window around the match was the first attempt and it was
#: far too generous: job postings say "preferred" and "or equivalent" constantly,
#: so a 220-character window found a hedge next to almost every requirement and
#: still flagged 78 of 400 postings. A requirement and a hedge two bullets apart
#: are two unrelated statements.
_CLAUSE_BOUNDARY = re.compile(r"[.\n\r;•·]|(?:^|\s)[-–—]\s")


def _enclosing_clause(text: str, start: int, end: int) -> str:
    """The sentence or bullet the match sits inside."""
    before = text[:start]
    boundaries = list(_CLAUSE_BOUNDARY.finditer(before))
    left = boundaries[-1].end() if boundaries else 0
    after = _CLAUSE_BOUNDARY.search(text, end)
    right = after.start() if after else len(text)
    return text[left:right]

#: How close the runner-up role family has to be before the two count as
#: contested. A share threshold on the leader alone was the first attempt and it
#: was wrong: with thirteen families, a leader holding 44% of the signal is
#: dominant, not contested, and the rule fired on 120 of 400 real postings. What
#: actually indicates a posting the parser cannot read is a near-tie, so the
#: test compares the two directly.
#:
#: 0.9 rather than a looser value, measured over the same 400 postings: at 0.75
#: this fired on 23.5% of them, at 0.9 on 15%, and below 0.9 most of what it
#: catches is a posting that genuinely spans two families rather than one the
#: parser cannot read. Tightening past 1.0 buys nothing (14.8%).
CONTESTED_FAMILY_RATIO = 0.9


@dataclass
class Uncertainty:
    """Why (or why not) this posting deserves a Gemini call."""

    ambiguous: bool
    reasons: list[str] = field(default_factory=list)
    primary_family: str = ""
    secondary_family: str = ""
    family_confidence: float = 0.0
    critical_requirements: list[str] = field(default_factory=list)
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguous": self.ambiguous,
            "reasons": self.reasons,
            "primaryFamily": self.primary_family,
            "secondaryFamily": self.secondary_family,
            "familyConfidence": round(self.family_confidence, 3),
            "criticalRequirements": self.critical_requirements,
            "score": self.score,
        }


def detect_role_families(text: str) -> tuple[str, str, float, float]:
    """(primary, secondary, primary share, runner-up ratio).

    The last value is what decides "contested": the runner-up's hits as a
    fraction of the leader's. 1.0 is a dead tie; a small number means the leader
    owns the posting even if its own share of the total is modest, which is the
    normal case once thirteen families are each picking up a stray keyword.
    """
    lowered = (text or "").lower()
    if not lowered.strip():
        return "", "", 0.0, 0.0

    hits: Counter[str] = Counter()
    for family, signals in ROLE_FAMILY_SIGNALS.items():
        for signal in signals:
            occurrences = lowered.count(signal)
            if occurrences:
                hits[family] += occurrences

    if not hits:
        return "", "", 0.0, 0.0

    ranked = hits.most_common()
    total = sum(hits.values())
    primary, primary_hits = ranked[0]
    secondary, secondary_hits = ranked[1] if len(ranked) > 1 else ("", 0)
    return (
        primary,
        secondary,
        primary_hits / total if total else 0.0,
        secondary_hits / primary_hits if primary_hits else 0.0,
    )


def find_critical_requirements(text: str, *, hedged_only: bool = True) -> list[str]:
    """Eligibility requirements the posting states.

    With `hedged_only` (the default) this returns just the ones stated
    ambiguously - the cases where a second opinion would actually change
    something. Pass False to see every stated requirement, which is what the
    diagnostics view wants.
    """
    lowered = (text or "").lower()
    found: list[str] = []
    for pattern, label in CRITICAL_REQUIREMENT_PATTERNS:
        match = re.search(pattern, lowered)
        if not match:
            continue
        if hedged_only:
            clause = _enclosing_clause(lowered, match.start(), match.end())
            if not _HEDGED_REQUIREMENT.search(clause):
                continue
        found.append(label)
    return found


def assess(
    job: dict[str, Any],
    *,
    score: float | None = None,
    auto_apply_score: float = AUTO_APPLY_SCORE,
    band: float = BOUNDARY_BAND,
    evidenced_terms: set[str] | None = None,
) -> Uncertainty:
    """Should this posting get a Gemini second opinion?

    Pure and cheap - string scanning over the posting text, no model, no I/O -
    so it is safe to run on every posting in the normal path. Only the postings
    it flags cost anything.
    """
    description = str(job.get("description") or job.get("snippet") or "")
    if score is None:
        raw = job.get("matchScore")
        score = float(raw) if isinstance(raw, (int, float)) else None

    primary, secondary, confidence, runner_up = detect_role_families(
        f"{job.get('title') or ''}\n{description}"
    )
    critical = find_critical_requirements(description)

    reasons: list[str] = []

    if score is None:
        reasons.append("posting has no deterministic match score")
    elif abs(score - auto_apply_score) <= band:
        reasons.append(
            f"score {score:.0f} is within {band:.0f} of the auto-apply boundary {auto_apply_score:.0f}"
        )

    if not primary:
        reasons.append("role family could not be determined from the posting")
    elif secondary and runner_up >= CONTESTED_FAMILY_RATIO:
        reasons.append(f"role family is contested between {primary} and {secondary}")

    # A critical requirement only makes the posting ambiguous when the
    # candidate's own evidence does not already settle it. Passing
    # `evidenced_terms` lets a profile that plainly holds a clearance skip the
    # call entirely.
    unresolved = [
        requirement for requirement in critical
        if not evidenced_terms or not any(word in evidenced_terms for word in requirement.split())
    ]
    if unresolved:
        reasons.append("posting states requirements the matcher cannot verify: " + ", ".join(unresolved))

    # A posting too short to describe anything is not ambiguous, it is empty.
    # Asking Gemini to judge 200 characters of boilerplate spends a call to be
    # told the posting is vague, which the length already said.
    if len(description.strip()) < 400:
        return Uncertainty(
            ambiguous=False,
            reasons=["posting is too short to judge; not worth an enrichment call"],
            primary_family=primary, secondary_family=secondary,
            family_confidence=confidence, critical_requirements=critical, score=score,
        )

    return Uncertainty(
        ambiguous=bool(reasons),
        reasons=reasons,
        primary_family=primary,
        secondary_family=secondary,
        family_confidence=confidence,
        critical_requirements=unresolved,
        score=score,
    )
