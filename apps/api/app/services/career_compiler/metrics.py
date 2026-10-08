"""Run splitting and text measurement shared by the DOCX renderer and the budget estimator.

Word decides the final layout; these Helvetica metrics only estimate line use before a render.
"""
from __future__ import annotations

import re

Run = tuple[str, bool]  # text, bold

WIN_ANSI_FALLBACK = {"\u2192": "->", "\u2190": "<-", "\u2011": "-", "\u00a0": " ", "\u2212": "-", "\u2248": "~",
                     "\u2265": ">=", "\u2264": "<=", "\u00d7": "x"}


def _safe(text: str) -> str:
    out = []
    for char in text:
        try:
            char.encode("cp1252")
            out.append(char)
        except UnicodeEncodeError:
            out.append(WIN_ANSI_FALLBACK.get(char, "?"))
    return "".join(out)


def width_of(runs: list[Run], size: float) -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth
    return sum(stringWidth(_safe(text), "Helvetica-Bold" if bold else "Helvetica", size) for text, bold in runs)


def wrap(runs: list[Run], width: float, size: float) -> list[list[Run]]:
    """Greedy word wrap across bold changes. Words glued across runs stay together."""
    groups: list[list[Run]] = []
    for text, bold in runs:
        for index, token in enumerate(re.findall(r"\s*\S+\s*|\s+", text)):
            if groups and index == 0 and not token[0].isspace() and not groups[-1][-1][0][-1:].isspace():
                groups[-1].append((token, bold))
            else:
                groups.append([(token.lstrip() if not groups else token, bold)])
    lines: list[list[Run]] = [[]]
    for group in groups:
        candidate = lines[-1] + group
        trimmed = candidate[:-1] + [(candidate[-1][0].rstrip(), candidate[-1][1])]
        if lines[-1] and width_of(trimmed, size) > width:
            lines.append([(group[0][0].lstrip(), group[0][1])] + group[1:])
        else:
            lines[-1] = candidate
    return lines


def line_count(runs: list[Run], width: float, size: float) -> tuple[int, float]:
    """Lines used and how full the last line is (0-1)."""
    lines = wrap(runs, width, size)
    return len(lines), (width_of(lines[-1], size) / width if lines and lines[-1] else 0)


def lead_runs(text: str, lead: dict) -> list[Run]:
    """Experience bullets: a bold lead clause up to the first comma or semicolon at least `min_chars` in."""
    for match in re.finditer(r"[,;]", text):
        if match.start() > lead["max_chars"]:
            break
        if match.start() >= lead["min_chars"]:
            return [(text[:match.start()], True), (text[match.start():], False)]
    return [(text, False)]


def summary_runs(text: str) -> list[Run]:
    """Summary: the first sentence is bold, its full stop and the rest are not."""
    match = re.search(r"\.\s+(?=[A-Z])", text)
    return [(text[:match.start()], True), (text[match.start():], False)] if match else [(text, False)]


def project_runs(name: str, text: str) -> list[Run]:
    return [(f"{name}:", True), (f" {text}", False)]


def skill_runs(label: str, items: list[str], separator: str) -> list[Run]:
    return [(label, True), (": " + separator.join(items), False)]
