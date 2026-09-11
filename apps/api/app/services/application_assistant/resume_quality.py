"""Is this tailored resume good enough to send to an employer?

The match score answers a different question. It reads the whole candidate
context - profile, accomplishments, resume - so a posting can score above the
bar while the document that would actually be attached is byte-identical to the
original, or is a rewrite with a sentence that stops mid-clause. Neither is
something to put in front of a hiring manager.

"Good" here means what the user asked for, in their words: structurally the same
as the original resume, no grammatical mistakes, more match than before, and no
gibberish. Each of those is a separate check below, and the report says which
one failed rather than returning a bare boolean, because the failure is the
useful part - it tells the retry what to fix and tells the user why nothing was
sent.

None of these checks can prove prose is well written. They are designed to catch
the specific ways a small local model degrades: truncation at a character
budget, doubled words, echoed input, dropped markup, and leftover JSON or
instruction fragments. A clean pass means nothing obviously broken got through,
not that the writing is good.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: A bullet must open with a bold lead phrase, as every bullet in the original
#: resume does. The renderer relies on it too.
_BOLD_LEAD = re.compile(r"^\s*<b>.+?</b>", re.S)

#: Sentence-final punctuation. A bullet clipped by the length clamp ends
#: mid-word or mid-clause instead, which is the most visible failure on a page.
_ENDS_CLEANLY = re.compile(r"[.!?%)\]]\s*$")

#: "the the", "and and" - the classic small-model stutter.
_DOUBLED_WORD = re.compile(r"\b(\w{3,})\s+\1\b", re.I)

#: Fragments of the prompt or of JSON that leaked into the answer.
_LEAKED = re.compile(
    r"(?:^\s*[\[\]{}\"]|```|\bLead Action Phrase\b|\bmax \d+ chars\b|"
    r"\bJSON array\b|\bbullet \[\d+\]|^\s*\d+\.\s*target)",
    re.I | re.M,
)

#: A run of letters too long to be a real English or technical word.
_LONG_RUN = re.compile(r"[A-Za-z]{26,}")

#: Words a finished sentence does not end on. A bullet stopping here has been
#: cut off mid-clause, whether or not something appended a full stop after.
_DANGLING_TAILS = frozenset(
    """
    a an the and or but with to of for in on at by from into across using
    via per plus including while where when that which who whose as than
    through toward towards under over between among during within without
    after before since about against upon onto off out up down
    """.split()
)


def strip_markup(text: str) -> str:
    return re.sub(r"<[^>]+>", "", str(text or "")).strip()


@dataclass
class QualityReport:
    ok: bool = True
    changed: int = 0
    total: int = 0
    score_before: float = 0.0
    score_after: float = 0.0
    problems: list[str] = field(default_factory=list)
    per_bullet: list[dict[str, Any]] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.ok = False
        if reason not in self.problems:
            self.problems.append(reason)

    def summary(self) -> str:
        if self.ok:
            return (
                f"{self.changed}/{self.total} bullets rewritten, "
                f"{self.score_before:.0f}% -> {self.score_after:.0f}%"
            )
        return "; ".join(self.problems)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "changed": self.changed,
            "total": self.total,
            "scoreBefore": self.score_before,
            "scoreAfter": self.score_after,
            "problems": list(self.problems),
            "perBullet": list(self.per_bullet),
        }


def inspect_bullet(tailored: str, original: str, *, max_chars: int) -> list[str]:
    """Structural and language problems in one rewritten bullet."""
    problems: list[str] = []
    text = str(tailored or "")
    plain = strip_markup(text)

    if not plain:
        return ["empty"]

    # --- structure: must look like the bullets already on the resume --------
    if not _BOLD_LEAD.search(text):
        problems.append("no bold lead phrase")
    if text.count("<b>") != text.count("</b>"):
        problems.append("unbalanced bold tags")
    if text.count("<b>") > 1:
        problems.append("more than one bold phrase")
    if len(plain) > max_chars:
        problems.append(f"too long ({len(plain)} > {max_chars})")

    # --- truncation: the most visible failure on the rendered page ----------
    if not _ENDS_CLEANLY.search(plain):
        problems.append("does not end in a complete sentence")
    # Check the last real word, not the punctuation. Testing the punctuated
    # string never matched, so "...create pull requests with automated." passed
    # as a complete sentence purely because something had appended a full stop
    # to a severed clause.
    tail = plain.rstrip(".!?;:, ").rsplit(" ", 1)[-1].lower()
    if tail in _DANGLING_TAILS:
        problems.append(f"ends on a dangling word ('{tail}')")

    # --- language ----------------------------------------------------------
    if _DOUBLED_WORD.search(plain):
        problems.append("repeated word")
    if _LEAKED.search(text):
        problems.append("leaked prompt or JSON fragment")
    if _LONG_RUN.search(plain):
        problems.append("unbroken letter run (likely gibberish)")
    if not plain[0].isupper() and not plain.startswith(("iOS", "eBay")):
        problems.append("does not start with a capital")

    # A rewrite that keeps almost none of the original's vocabulary has usually
    # drifted onto a different subject rather than reframed this one.
    original_words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", strip_markup(original))}
    tailored_words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", plain)}
    if original_words and len(original_words & tailored_words) / len(original_words) < 0.2:
        problems.append("shares almost no vocabulary with the original")

    return problems


def assess(
    master_bullets: list[str],
    tailored_bullets: list[str],
    *,
    score_before: float,
    score_after: float,
    min_changed: int = 3,
    require_improvement: bool = True,
    length_budget: int = 20,
) -> QualityReport:
    """Decide whether this tailored resume is fit to submit."""
    report = QualityReport(
        total=len(master_bullets),
        score_before=float(score_before or 0.0),
        score_after=float(score_after or 0.0),
    )

    if len(tailored_bullets) != len(master_bullets):
        report.fail(
            f"expected {len(master_bullets)} bullets, got {len(tailored_bullets)}"
        )
        return report

    for idx, (tailored, original) in enumerate(zip(tailored_bullets, master_bullets)):
        budget = len(strip_markup(original)) + length_budget
        problems = inspect_bullet(tailored, original, max_chars=budget)
        is_changed = strip_markup(tailored) != strip_markup(original)
        if is_changed:
            report.changed += 1
        if problems:
            report.per_bullet.append(
                {"index": idx + 1, "changed": is_changed, "problems": problems}
            )
            # An untouched original carrying a complaint is the original's own
            # business, not this rewrite's - only judge what was rewritten.
            if is_changed:
                report.fail(f"bullet {idx + 1}: {', '.join(problems)}")

    if report.changed < min_changed:
        report.fail(
            f"only {report.changed} of {report.total} bullets rewritten "
            f"(need {min_changed}) - this is effectively the original resume"
        )

    if require_improvement and report.score_after <= report.score_before:
        report.fail(
            f"match did not improve ({report.score_before:.0f}% -> "
            f"{report.score_after:.0f}%)"
        )

    return report
