"""Writing-style lint. It flags generic AI-resume phrasing and may request a rewrite; it never edits facts."""
from __future__ import annotations

import re
from collections import Counter

from app.services.career_compiler.models import Bullet
from app.services.career_compiler.validator import numbers

#: (pattern, code, severity, message). "rewrite" asks DeepSeek for a style-only rewrite; "flag" only reports.
PHRASES = (
    (r"\bleverag(e|ed|es|ing)\b", "cliche", "rewrite", "'leverage' adds nothing; name what was used and how."),
    (r"\butiliz(e|ed|es|ing)\b", "cliche", "rewrite", "Use 'used' or name the mechanism."),
    (r"\bcutting[- ]edge\b", "cliche", "rewrite", "Unsupported adjective."),
    (r"\binnovative( solution)?s?\b", "cliche", "rewrite", "Unsupported adjective."),
    (r"\btransformative\b", "cliche", "rewrite", "Unsupported adjective."),
    (r"\brevolutioni[sz](e|ed|ing)\b", "cliche", "rewrite", "Unsupported claim."),
    (r"\bspearhead(ed|ing)?\b", "cliche", "rewrite", "Say what you built or led."),
    (r"\bstate[- ]of[- ]the[- ]art\b|\bworld[- ]class\b|\bbest[- ]in[- ]class\b", "cliche", "rewrite", "Unsupported adjective."),
    (r"\bseamless(ly)?\b|\bsynerg(y|ies)\b|\brobust and scalable\b", "cliche", "flag", "Generic phrasing."),
    (r"\butiliz\w*\b.*\bto (optimize|improve|enhance)\b|\bleverag\w*\b.*\bto (optimize|improve|enhance)\b",
     "formula", "rewrite", "The 'used X to optimize Y' formula."),
    (r",\s*resulting in\b", "trailing_result", "flag", "'resulting in' often adds no information."),
    (r",\s*(showcasing|demonstrating|highlighting|underscoring)\b", "filler_clause", "rewrite", "Filler clause."),
    (r"\bin order to\b", "wordy", "flag", "'in order to' can be 'to'."),
)


def _opening(text: str) -> str:
    match = re.match(r"\s*([A-Za-z-]+)", text)
    return match.group(1).casefold() if match else ""


def lint(bullets: list[Bullet]) -> dict[str, list[dict[str, str]]]:
    """Per-bullet findings. Repetition checks look across the whole resume."""
    findings: dict[str, list[dict[str, str]]] = {b.id: [] for b in bullets}
    for bullet in bullets:
        for pattern, code, severity, message in PHRASES:
            if re.search(pattern, bullet.text, re.I):
                findings[bullet.id].append({"code": code, "severity": severity, "message": message})
    openers = Counter(_opening(b.text) for b in bullets if b.id != "summary")
    seen: Counter[str] = Counter()
    for bullet in bullets:
        if bullet.id == "summary":
            continue
        verb = _opening(bullet.text)
        seen[verb] += 1
        if verb and openers[verb] >= 3 and seen[verb] >= 3:
            findings[bullet.id].append({"code": "repeated_opening", "severity": "rewrite",
                                        "message": f"'{verb.capitalize()}' already opens {seen[verb] - 1} bullets."})
    trailing = [b for b in bullets if re.search(r",\s+\w+ing\b[^,;]*\.?$", b.text) and b.id != "summary"]
    if len(bullets) >= 4 and len(trailing) > len(bullets) / 2:
        for bullet in trailing[len(bullets) // 2:]:
            findings[bullet.id].append({"code": "uniform_structure", "severity": "flag",
                                        "message": "Most bullets end with the same ', …ing …' clause."})
    return findings


def needs_rewrite(issues: list[dict[str, str]]) -> bool:
    return any(i["severity"] == "rewrite" for i in issues)


def same_facts(original: Bullet, rewritten: Bullet, technologies: tuple[str, ...]) -> bool:
    """A style rewrite may not add or remove numbers, technologies or citations."""
    from app.services.career_compiler.lexicon import mentions_tech
    if set(rewritten.evidence_ids) != set(original.evidence_ids):
        return False
    if numbers(rewritten.text) != numbers(original.text):
        return False
    before = {t for t in technologies if mentions_tech(original.text, t)}
    after = {t for t in technologies if mentions_tech(rewritten.text, t)}
    return after <= before
